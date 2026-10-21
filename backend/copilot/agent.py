#
# Ask Prosper AI: a chat about an agent, outside any pull request, where
# Prosper AI answers and does what the person can do in the product ("Can
# Anna book for a child?", "open an issue for what the clinic emailed",
# "snooze the wording issues for a week", "merge PR #5").
#
# Every answer starts from the facts about this agent, written into the
# first message: the guidelines, the copy the person is looking at (live, or
# the pull request they are on) with its rules, its tests and how they last
# went, the versions, pull requests and issues, how many calls there were and
# how they went, the latest calls one line each, and whole the calls the chat
# names. Most questions are answered from those alone, in one request.
#
# Then tools (api/tools.py), on the OpenAI Agents SDK: an Agent whose tools
# are those, one call per step and at most MAX_TOOL_CALLS per message. A tool
# that reads (search calls, read an issue, read a pull request's tests) runs
# at once and its result goes back to the model; the chat shows a muted line
# for it ("Read Issue #5 and its 3 calls"). A tool that acts needs approval:
# the run stops at it, and the message ends with its card ("Open issue:
# Books under the parent's name · Collect details · Booking") and the run's
# state, serialised, kept on the message, so a restart loses no card. When
# the person clicks Do it, the state is loaded and approved (`decide`): the
# tool runs, the card says what happened, and the run goes on with the
# result, so Prosper AI can say what is next or propose the next step. Cancel
# only marks the card: the next question tells Prosper AI it was declined.
# Nothing changes from a chat without a click.
#
# Each tool is a route the UI calls, called as a function: the same checks,
# and the same 404/409/422 sentences, which go back to the model as the
# tool's refusal for it to correct or explain.
#
# The final answer is checked in code like any artifact: short, steps named
# as words, and every issue, pull request or call it links to one that exists.
#

import asyncio
import json
import re
import time
from dataclasses import dataclass, replace
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
    set_tracing_disabled,
)
from agents.exceptions import AgentsException
from agents.run_error_handlers import RunErrorHandlerInput, RunErrorHandlerResult
from agents.tool_context import ToolContext
from loguru import logger
from openai.types.shared import Reasoning
from pydantic import BaseModel

import store
from store.prosper import PROSPER

from . import facts, llm
from .llm import ATTEMPTS, EFFORT, MAX_TOKENS, Failed, prompt

set_tracing_disabled(True)  # nothing of a chat leaves through the SDK's tracing

MAX_ANSWER_CHARS = 600
MAX_TITLE_CHARS = 60
MAX_LINKS = 4
MAX_TOOL_CALLS = 8  # per message: past them, it answers with what it has


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


@dataclass(frozen=True)
class Tool:
    """Something Prosper AI can do in a chat: read, or act once the person says so."""

    name: str
    about: str  # what the model reads about it
    params: dict  # its arguments, as a strict JSON schema
    # A read: (agent id, arguments) -> what the model reads, and the line the chat shows.
    read: Optional[Callable[[str, dict], tuple[str, str]]] = None
    # An act: its card, { title, what, meta, warnings? }, made before anything
    # is done; it raises ToolError when the act would be refused, so the model
    # hears it before the person does.
    card: Optional[Callable[[str, dict], dict]] = None
    # And doing it, once the person says so: (agent id, arguments, { chat,
    # message, warnings: the card's }) -> { text, link, said }: what the card
    # then says, what it links to, and what the model is told.
    act: Optional[Callable[[str, dict, dict], dict]] = None


def answer(agent_id: str, chat_id: int, about: tuple[dict, str], tools: dict[str, Tool]) -> dict:
    """Answer the chat's last message, about the copy `about` (from `copy_of`).

    Returns the chat with Prosper AI's message added: its answer, or the
    action it proposes. A model that gives no answer that passes its check
    is said in the chat, as Prosper AI's message.
    """
    chat = store.chats.get_chat(agent_id, chat_id)
    copy, name = about
    model = llm.new_llm()
    start = [{"role": "user", "content": facts.for_chat(agent_id, copy, name, chat["messages"])}]
    message = asyncio.run(_converse(_agent(tools, model), model, name, start, _scope(agent_id)))
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
        follow = asyncio.run(_resume(_agent(tools, model), model, message["about"], saved, scope))
    except Exception:  # noqa: BLE001 - what was done is done; the rest is a nicety
        logger.exception("Ask Prosper AI · could not go on after an action")
    if not scope["settled"]:
        _settle(scope, None, "It could not be done: the conversation could not be picked up.")
    if follow is None:
        return store.chats.get_chat(agent_id, chat_id)
    return store.chats.add_message(agent_id, chat_id, follow, model.usage)


def _scope(agent_id: str, at: Optional[dict] = None) -> dict:
    """What a run's tools share: the agent, the lines it read, the cards it made.

    `at`: the card being done, once the person said Do it.
    """
    return {"agent_id": agent_id, "reads": [], "cards": {}, "at": at, "settled": False}


# Low effort, one tool call at a time (an act waits for the person, and
# whatever came with it would wait too), and nothing kept at OpenAI: the
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


def _agent(tools: dict[str, Tool], model) -> Agent:
    return Agent(
        name=PROSPER,
        instructions=prompt("ask"),
        model=model.agent_model(),
        model_settings=_SETTINGS,
        tools=[_function(tool) for tool in tools.values()],
        output_type=_Said,
    )


def _function(tool: Tool) -> FunctionTool:
    """`tool` as the SDK runs it: a read at once; an act once the person approves its card."""

    async def invoke(call: ToolContext, arguments: str) -> str:
        scope = call.context
        args = json.loads(arguments)
        try:
            if tool.read is not None:
                output, line = tool.read(scope["agent_id"], args)
                scope["reads"].append(line)
                return output
            if refused := scope["cards"].get(call.tool_call_id, {}).get("refused"):
                return f"Refused: {refused}"
            return _act(tool, scope, args)
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


class _Counted(RunHooks):
    """Every request of a run counted and priced on `model`, and logged with its time."""

    def __init__(self, model):
        self.model = model
        self.started = 0.0

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.started = time.monotonic()

    async def on_llm_end(self, context, agent, response) -> None:
        self.model.count(response.usage)
        calls = [item.name for item in response.output if item.type == "function_call"]
        did = f"calls {calls[0]}" if calls else "answers"
        logger.info(f"Prosper AI · ask · {did} · {time.monotonic() - self.started:.1f}s")


async def _resume(agent: Agent, model, name: str, saved: dict, scope: dict) -> Optional[dict]:
    """Pick up the run kept with a card, its act approved: the act runs, then the run goes on."""
    state = await RunState.from_json(agent, saved, context_override=scope)
    for pending in state.get_interruptions():
        state.approve(pending)
    return await _converse(agent, model, name, state, scope, after_action=True)


async def _converse(
    agent: Agent, model, name: str, start, scope: dict, after_action: bool = False
) -> Optional[dict]:
    """Run the agent from `start` (the facts, or a run picked up) until it answers or proposes
    an act: its message.

    At most MAX_TOOL_CALLS tool calls, then it answers with what it has.
    After an action, Prosper AI may have nothing to add: then None.
    """
    hooks = _Counted(model)
    quiet = agent.clone(model_settings=replace(_SETTINGS, tool_choice="none"))
    base = {"by": PROSPER, "about": name, "links": [], "reads": scope["reads"]}

    async def answer_now(error: RunErrorHandlerInput) -> RunErrorHandlerResult:
        said = await Runner.run(
            quiet, error.run_data.history, context=scope, max_turns=1, hooks=hooks, run_config=_RUN
        )
        return RunErrorHandlerResult(final_output=said.final_output)

    try:
        result = await Runner.run(
            agent,
            start,
            # A run picked up has its own, with the approval in it.
            context=None if isinstance(start, RunState) else scope,
            max_turns=MAX_TOOL_CALLS,
            hooks=hooks,
            run_config=_RUN,
            error_handlers={"max_turns": answer_now},
        )
        for attempt in range(1, ATTEMPTS + 1):
            if result.interruptions:
                return {**base, "text": "", **_proposed(result)}
            said = result.final_output.model_dump()
            if after_action and not said["answer"].strip():
                return None
            try:
                check_answer(said, _known(scope["agent_id"]))
                return {**base, "text": said["answer"], "links": _unique(said["links"])}
            except ValueError as error:
                if attempt == ATTEMPTS:
                    raise Failed(str(error)) from error
                again = f"That was refused: {error}\nFix it and answer again with the whole JSON."
                items = [*result.to_input_list(), {"role": "user", "content": again}]
                result = await Runner.run(
                    quiet, items, context=scope, max_turns=1, hooks=hooks, run_config=_RUN
                )
    except (Failed, AgentsException) as error:
        return {**base, "text": f"I couldn't answer that: {error} Ask me again.", "failed": True}


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
