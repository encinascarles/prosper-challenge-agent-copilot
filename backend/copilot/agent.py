#
# Prosper AI: one agent, on the OpenAI Agents SDK, with one set of tools
# (api/tools.py), working in two places.
#
# In a chat (Ask Prosper AI), outside any pull request, it answers and does
# what the person can do in the product ("Can Anna book for a child?", "open
# an issue for what the clinic emailed", "merge PR #5"). Every answer starts
# from the facts about the agent (facts.py); most questions are answered from
# those alone. A tool that reads runs at once, and the chat shows a muted line
# for it ("Read Issue #5 and its 3 calls"). A tool that acts needs approval:
# the run stops at it, and the message ends with its card and the run's
# state, serialised, kept on the message, so a restart loses no card. When the
# person clicks Do it, the state is loaded and approved (`decide`): the tool
# runs, the card says what happened, and the run goes on with the result.
# Cancel only marks the card. Nothing changes from a chat without a click; a
# change to the agent itself is a pull request, where Prosper AI goes on.
#
# In a pull request's conversation, it works on that pull request's copy: it
# reads, edits the copy in small pieces (a step's task, a rule, a test), runs
# its tests and asks the person questions, with no card, since nothing there
# reaches callers before a person merges it: the pull request is the review.
# A setup, a fix and a change are not separate programs: they are how the
# work starts, a brief (prompts/setup.md, fix.md, change.md) given to the same
# agent with the facts of the pull request. A message from the person (an
# answer, "make the greeting shorter") is the next turn of the same work. The
# guarantees are in the tools (copilot/work.py): what they refuse goes back to
# the model as the tool's error, in the sentence a person would read.
#
# A turn runs as a background job on a small pool; its tests run on the
# checks' loop, and the tool waits for them. Every turn starts from what the
# store holds (the copy, the conversation, where the work stands), never
# from memory: a question asked ends the turn and its answer starts the next,
# and a turn cut by a restart is picked up by the next message.
#
# What a person reads from it is checked in code like any artifact: short,
# steps named as words, and every issue, pull request or call it links to
# one that exists.
#

import asyncio
import json
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Callable, Literal, Optional

from agents import (
    Agent,
    FunctionTool,
    ModelSettings,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    Runner,
    RunState,
    ToolsToFinalOutputResult,
    set_tracing_disabled,
)
from agents.exceptions import AgentsException
from agents.run_error_handlers import RunErrorHandlerInput, RunErrorHandlerResult
from agents.tool_context import ToolContext
from loguru import logger
from openai.types.shared import Reasoning
from pydantic import BaseModel

import store
from store.db import now
from store.prosper import PROSPER

from . import facts, llm
from .llm import ATTEMPTS, EFFORT, LLM, MAX_TOKENS, Failed, prompt

set_tracing_disabled(True)  # nothing of a chat or a call leaves through the SDK's tracing

MAX_ANSWER_CHARS = 600
MAX_TITLE_CHARS = 60
MAX_LINKS = 4
MAX_TOOL_CALLS = 8  # per chat message: past them, it answers with what it has
# Per turn of work on a pull request. A setup takes about 12 (draw, rules,
# tests, run, two rounds of reading a failing call and changing a piece, its
# message) and a fix about 10; 30 leaves room for reads and refused edits
# while bounding what a turn that goes in circles can cost.
MAX_TURNS_AT_WORK = 30
# The brief a pull request's work starts from, by its kind.
BRIEFS = {"setup": "setup", "fix": "fix", "change": "change", "edit": "change"}


class _Link(BaseModel):
    kind: Literal["issue", "pull", "call"]
    number: int  # the issue's or pull request's number, or the call's id


class _Said(BaseModel):
    """An answer: its words, and what it names that can be opened."""

    answer: str
    links: list[_Link]


# A name as the store keeps it, snake_case: never what a person reads.
_STORED_NAME = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


class ToolError(Exception):
    """A tool refused: the sentence says why, and goes back to the model."""


@dataclass
class Work:
    """A turn of Prosper AI's work on a pull request, as its tools share it."""

    agent_id: str
    number: int
    model: LLM
    runs: int = 0  # whole runs of the copy's tests this turn
    waiting: bool = False  # it asked the person something: the turn ends there
    reads: list = field(default_factory=list)


@dataclass(frozen=True)
class Tool:
    """Something Prosper AI can do: read, act once the person says so, or edit its copy."""

    name: str
    about: str  # what the model reads about it
    params: dict  # its arguments, as a strict JSON schema
    # A read, in a chat and in a pull request: (agent id, arguments) -> what
    # the model reads, and the line the person sees for it.
    read: Optional[Callable[[str, dict], tuple[str, str]]] = None
    # An act, in a chat: its card, { title, what, meta, warnings? }, made
    # before anything is done; it raises ToolError when the act would be
    # refused, so the model hears it before the person does.
    card: Optional[Callable[[str, dict], dict]] = None
    # And doing it, once the person says so: (agent id, arguments, { chat,
    # message, warnings: the card's }) -> { text, link, said }: what the card
    # then says, what it links to, and what the model is told.
    act: Optional[Callable[[str, dict, dict], dict]] = None
    # Work on a pull request's copy, done at once: (work, arguments) -> what
    # the model is told. It writes to the conversation itself.
    edit: Optional[Callable[[Work, dict], str]] = None
    doing: str = "Working on it"  # an edit's spinner while it runs


def _tools(tools: dict[str, Tool], where: str) -> list[Tool]:
    if where == "chat":
        return [tool for tool in tools.values() if tool.edit is None]
    return [tool for tool in tools.values() if tool.act is None]


# ---- in a chat ----------------------------------------------------------------


def answer(agent_id: str, chat_id: int, about: tuple[dict, str], tools: dict[str, Tool]) -> dict:
    """Answer the chat's last message, about the copy `about` (from `facts.copy_of`).

    Returns the chat with Prosper AI's message added: its answer, or the
    action it proposes. A model that gives no answer that passes its check
    is said in the chat, as Prosper AI's message.
    """
    chat = store.chats.get_chat(agent_id, chat_id)
    copy, name = about
    model = llm.new_llm()
    start = [{"role": "user", "content": facts.for_chat(agent_id, copy, name, chat["messages"])}]
    message = asyncio.run(_chat(_agent(tools, model, "chat"), model, name, start, _scope(agent_id)))
    return store.chats.add_message(agent_id, chat_id, message, model.usage)


def decide(agent_id: str, chat_id: int, index: int, do: bool, tools: dict[str, Tool]) -> dict:
    """Do (`do`) or decline the action message `index` proposes. Returns the chat.

    Done, its result goes back to Prosper AI, whose next message (if it has
    one) is added. Raises NotFound, or Conflict when it was decided already.
    """
    message = store.chats.claim_action(agent_id, chat_id, index, do)
    if not do:
        return store.chats.get_chat(agent_id, chat_id)
    action = message["action"]
    # The warnings its card showed: the click on Do it was made reading them.
    at = {"chat": chat_id, "message": index, "warnings": action.get("warnings", [])}
    scope = _scope(agent_id, at)
    saved = (message.get("resume") or {}).get("state")
    if saved is None:
        # A card from before the run was kept with it: done, with nothing to go on from.
        _act(tools[action["tool"]], scope, action["args"])
        return store.chats.get_chat(agent_id, chat_id)
    model = llm.new_llm()
    follow = None
    try:
        agent = _agent(tools, model, "chat")
        follow = asyncio.run(_resume(agent, model, message["about"], saved, scope))
    except Exception:  # noqa: BLE001 - what was done is done; the rest is a nicety
        logger.exception("Ask Prosper AI · could not go on after an action")
    if not scope["settled"]:
        _settle(scope, None, "It could not be done: the conversation could not be picked up.")
    if follow is None:
        return store.chats.get_chat(agent_id, chat_id)
    return store.chats.add_message(agent_id, chat_id, follow, model.usage)


async def _resume(agent: Agent, model: LLM, name: str, saved: dict, scope: dict) -> Optional[dict]:
    """Pick up the run kept with a card, its act approved: the act runs, then the run goes on."""
    state = await RunState.from_json(agent, saved, context_override=scope)
    for pending in state.get_interruptions():
        state.approve(pending)
    return await _chat(agent, model, name, state, scope, after_action=True)


def _scope(agent_id: str, at: Optional[dict] = None) -> dict:
    """What a chat's tools share: the agent, the lines it read, the cards it made.

    `at`: the card being done, once the person said Do it.
    """
    return {"agent_id": agent_id, "reads": [], "cards": {}, "at": at, "settled": False}


async def _chat(
    agent: Agent, model: LLM, name: str, start, scope: dict, after_action: bool = False
) -> Optional[dict]:
    """The chat's next message: an answer, or the card of the act the run stopped at.

    After an action, Prosper AI may have nothing to add: then None.
    """
    base = {"by": PROSPER, "about": name, "links": [], "reads": scope["reads"]}
    try:
        result, said = await _converse(agent, model, start, scope, MAX_TOOL_CALLS, after_action)
    except (Failed, AgentsException) as error:
        return {**base, "text": f"I couldn't answer that: {error} Ask me again.", "failed": True}
    if result.interruptions:
        return {**base, "text": "", **_proposed(result)}
    if said is None:
        return None
    return {**base, "text": said["answer"], "links": _unique(said["links"])}


def _act(tool: Tool, scope: dict, args: dict) -> str:
    """Do the act the person approved, and write on its card how it went: what the model is told."""
    done, error = None, None
    try:
        done = tool.act(scope["agent_id"], args, scope["at"])
    except ToolError as refused:
        error = str(refused)
    except Exception as failure:  # noqa: BLE001 - the card must not stay "running"
        logger.exception(f"Ask Prosper AI · {tool.name} failed")
        error = f"It could not be done: {failure}"
    _settle(scope, {"text": done["text"], "link": done.get("link")} if done else None, error)
    return done["said"] if done else f"Refused: {error}"


def _settle(scope: dict, result: Optional[dict], error: Optional[str]) -> None:
    at = scope["at"]
    store.chats.settle_action(scope["agent_id"], at["chat"], at["message"], result, error)
    scope["settled"] = True


def _proposed(result) -> dict:
    """The card of the act the run stopped at, and the run, kept to pick up on Do it."""
    pending = result.interruptions[0]
    call = pending.raw_item
    card = result.context_wrapper.context["cards"][call.call_id]
    action = {"tool": pending.tool_name, "args": json.loads(call.arguments), **card}
    return {
        "action": {**action, "state": "pending"},
        "resume": {"state": result.to_state().to_json()},
    }


# ---- in a pull request ----------------------------------------------------------

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prosper")
_jobs: list[Future] = []
_lock = threading.Lock()


def start(agent_id: str, number: int, said: Optional[str] = None) -> Future:
    """Run a turn of Prosper AI's work on pull request `number`, in the background.

    `said`: what the person wrote, or the answer they gave, that starts it;
    None to start the work its brief describes, or go on with it.
    """
    future = _pool.submit(_guarded, agent_id, number, said)
    with _lock:
        _jobs[:] = [job for job in _jobs if not job.done()] + [future]
    return future


def wait(timeout: float = 30) -> None:
    """Wait for the turns in progress to finish. For tests."""
    with _lock:
        jobs = list(_jobs)
    for job in jobs:
        job.result(timeout)


def _guarded(agent_id: str, number: int, said: Optional[str]) -> None:
    from api.tools import (
        TOOLS,
    )  # the routes it calls are the API's; imported late, they import this

    model = llm.new_llm()
    try:
        asyncio.run(_turn(agent_id, number, TOOLS, said, model))
    except Exception as error:  # noqa: BLE001 - said in the conversation, never lost in a thread
        logger.exception(f"Prosper AI could not finish on agent {agent_id}")
        reason = str(error) or type(error).__name__
        reason = reason if len(reason) <= 200 else reason[:199] + "…"
        text = f"I couldn't finish: {reason} Write to me to try again, or say what to change."
        try:
            store.prosper.log(agent_id, number, _event("message", text=text))
            store.prosper.set_state(agent_id, number, "failed")
        except (store.NotFound, store.Conflict):
            pass  # the agent was deleted meanwhile, or the pull request closed
    finally:
        logger.info(f"Prosper AI spent on agent {agent_id}: {model.usage}")
        try:
            store.prosper.spend(agent_id, number, model.usage)
        except store.NotFound:
            pass


def _event(kind: str, **more) -> dict:
    return {"type": kind, "by": PROSPER, "at": now(), **more}


async def _turn(
    agent_id: str, number: int, tools: dict[str, Tool], said: Optional[str], model: LLM
) -> None:
    from api import checks  # the API runs the checks; imported late, it also mounts this

    from . import work as working  # its guards stand on this module's Work and ToolError

    pull = store.get_pull(agent_id, number)
    work = Work(agent_id, number, model)
    agent = _agent(tools, model, "pull", BRIEFS[pull["kind"]])
    start = [{"role": "user", "content": facts.at_work(agent_id, pull, said)}]
    try:
        _, answered = await _converse(agent, model, start, work, MAX_TURNS_AT_WORK)
        text = answered["answer"] if answered else ""
    except Failed as error:
        text = f"I couldn't say it in a way that passes my checks: {error}"
    if work.waiting:
        return  # its question is in the conversation; the answer starts the next turn
    pull = store.get_pull(agent_id, number)
    if pull["state"] != "open":
        return
    if text or store.prosper.unsaid(agent_id, number):
        # What it changed since it last said why goes under its last word, as a
        # proposed change on a fix: the card a fix's conversation shows.
        proposing = pull["kind"] != "setup" and store.prosper.unsaid(agent_id, number)
        said_event = _event("proposed" if proposing else "message", text=text or "Done.")
        store.prosper.say(agent_id, number, said_event)
    store.prosper.set_state(agent_id, number, "done")
    if pull["tests"] and working.ready(agent_id, pull):
        # What can merge has passed its suite on the copy as it is now: kept
        # when it already ran on it, run when the last change came after.
        checks.start(agent_id, pull=number)


def _agent(tools: dict[str, Tool], model: LLM, where: str, brief: Optional[str] = None) -> Agent:
    instructions = [prompt("prosper"), prompt("ask" if where == "chat" else "pull")]
    if brief:
        instructions.append(prompt(brief))
    return Agent(
        name=PROSPER,
        instructions="\n\n".join(instructions),
        model=model.agent_model("ask" if where == "chat" else "work"),
        model_settings=_SETTINGS,
        tools=[_function(tool) for tool in _tools(tools, where)],
        output_type=_Said,
        tool_use_behavior=_stop_when_waiting,
    )


def _stop_when_waiting(run: RunContextWrapper, results) -> ToolsToFinalOutputResult:
    # A question to the person ends the turn: its answer starts the next.
    if isinstance(run.context, Work) and run.context.waiting:
        return ToolsToFinalOutputResult(is_final_output=True, final_output=None)
    return ToolsToFinalOutputResult(is_final_output=False)


# Low effort, one tool call at a time (an act waits for the person, and an edit
# reads the copy the last one wrote), and nothing kept at OpenAI: the
# organization's key has zero data retention, so the whole conversation is
# sent each step, its reasoning encrypted, and the run is kept on our side.
_SETTINGS = ModelSettings(
    reasoning=Reasoning(effort=EFFORT),
    max_tokens=MAX_TOKENS,
    parallel_tool_calls=False,
    store=False,
    response_include=["reasoning.encrypted_content"],
)
# No call data leaves through tracing: the SDK's export to OpenAI is off.
_RUN = RunConfig(tracing_disabled=True, tool_not_found_behavior="return_error_to_model")


def _function(tool: Tool) -> FunctionTool:
    """`tool` as the SDK runs it: a read or an edit at once; an act once the person approves."""

    async def invoke(call: ToolContext, arguments: str) -> str:
        context = call.context
        args = json.loads(arguments)
        try:
            if isinstance(context, Work):
                return await _at_work(tool, context, args)
            if tool.read is not None:
                output, line = await asyncio.to_thread(tool.read, context["agent_id"], args)
                context["reads"].append(line)
                return output
            if refused := context["cards"].get(call.tool_call_id, {}).get("refused"):
                return f"Refused: {refused}"
            return await asyncio.to_thread(_act, tool, context, args)
        except ToolError as error:
            return f"Refused: {error}"

    async def needs_approval(run: RunContextWrapper, args: dict, call_id: str) -> bool:
        # The card is made here, before anything is done; an act it would be
        # refused for is not put to the person: the refusal goes to the model.
        scope = run.context
        try:
            scope["cards"][call_id] = tool.card(scope["agent_id"], args)
        except ToolError as error:
            scope["cards"][call_id] = {"refused": str(error)}
            return False
        return True

    return FunctionTool(
        name=tool.name,
        description=tool.about,
        params_json_schema=tool.params,
        on_invoke_tool=invoke,
        strict_json_schema=True,
        needs_approval=needs_approval if tool.act is not None else False,
    )


async def _at_work(tool: Tool, work: Work, args: dict) -> str:
    """A tool in a pull request: a read is said as a step of the work, an edit runs at once."""
    if tool.read is not None:
        output, line = await asyncio.to_thread(tool.read, work.agent_id, args)
        if line not in work.reads:
            work.reads.append(line)
            store.prosper.log(work.agent_id, work.number, _event("step", text=line))
        return output
    store.prosper.set_state(work.agent_id, work.number, "working", tool.doing)
    return await asyncio.to_thread(tool.edit, work, args)


class _Counted(RunHooks):
    """Every request of a run counted and priced on `model`, and logged with its time."""

    def __init__(self, model: LLM):
        self.model = model
        self.started = 0.0

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.started = time.monotonic()

    async def on_llm_end(self, context, agent, response) -> None:
        self.model.count(response.usage)
        calls = [item.name for item in response.output if item.type == "function_call"]
        did = f"calls {calls[0]}" if calls else "answers"
        where = "work" if isinstance(context.context, Work) else "ask"
        logger.info(f"Prosper AI · {where} · {did} · {time.monotonic() - self.started:.1f}s")


async def _converse(
    agent: Agent, model: LLM, start, context, max_turns: int, after_action: bool = False
) -> tuple:
    """Run the agent from `start` (the facts, or a run picked up) until it answers, stops at
    an act to approve, or asks the person: the run's result, and its answer if it gave one.

    At most `max_turns` requests, then it answers with what it has. An answer
    that fails its check goes back with the error, ATTEMPTS times at most,
    then Failed. After an action, an empty answer is nothing to add: None.
    """
    hooks = _Counted(model)
    quiet = agent.clone(model_settings=replace(_SETTINGS, tool_choice="none"))
    agent_id = context.agent_id if isinstance(context, Work) else context["agent_id"]

    async def answer_now(error: RunErrorHandlerInput) -> RunErrorHandlerResult:
        said = await Runner.run(
            quiet,
            error.run_data.history,
            context=context,
            max_turns=1,
            hooks=hooks,
            run_config=_RUN,
        )
        return RunErrorHandlerResult(final_output=said.final_output)

    result = await Runner.run(
        agent,
        start,
        # A run picked up has its own, with the approval in it.
        context=None if isinstance(start, RunState) else context,
        max_turns=max_turns,
        hooks=hooks,
        run_config=_RUN,
        error_handlers={"max_turns": answer_now},
    )
    for attempt in range(1, ATTEMPTS + 1):
        if result.interruptions or result.final_output is None:
            return result, None
        said = result.final_output.model_dump()
        if after_action and not said["answer"].strip():
            return result, None
        try:
            check_answer(said, _known(agent_id))
            return result, said
        except ValueError as error:
            if attempt == ATTEMPTS:
                raise Failed(str(error)) from error
            again = f"That was refused: {error}\nFix it and answer again with the whole JSON."
            items = [*result.to_input_list(), {"role": "user", "content": again}]
            result = await Runner.run(
                quiet, items, context=context, max_turns=1, hooks=hooks, run_config=_RUN
            )
    return result, None


def check_answer(answer: dict, known: dict) -> None:
    """Raise ValueError with what is wrong: too long, a stored name, a link to nothing."""
    text = answer["answer"].strip()
    if not text:
        raise ValueError("The answer is empty.")
    if len(text) > MAX_ANSWER_CHARS:
        raise ValueError(
            f"The answer is {len(text)} characters: say it in at most {MAX_ANSWER_CHARS}."
        )
    if found := _STORED_NAME.search(text):
        raise ValueError(f'Name steps and fields as words, never "{found.group()}".')
    if len(answer["links"]) > MAX_LINKS:
        raise ValueError(f"Link at most {MAX_LINKS} things: the ones the answer names.")
    for link in answer["links"]:
        if link["number"] not in known[link["kind"]]:
            what = {"issue": "Issue #{}", "pull": "PR #{}", "call": "call {}"}[link["kind"]]
            raise ValueError(f"There is no {what.format(link['number'])}: link only what exists.")


def _unique(links: list[dict]) -> list[dict]:
    seen = []
    for link in links:
        if link not in seen:
            seen.append(link)
    return seen


def _known(agent_id: str) -> dict:
    """What an answer may link to, by kind: the numbers that exist."""
    return {
        "issue": {issue["number"] for issue in store.issues.list_issues(agent_id)},
        "pull": {pull["number"] for pull in store.list_pulls(agent_id)},
        "call": {call["id"] for call in store.calls.list_calls(agent_id)},
    }
