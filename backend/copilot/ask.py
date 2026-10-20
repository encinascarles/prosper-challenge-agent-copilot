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
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Optional

from agents import (
    Agent,
    AgentOutputSchemaBase,
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

import store
from simulate.suite import REPEATS
from store.prosper import PROSPER
from store.runs import verdict

from . import setup
from .artifacts import _list, _object
from .calls import _ENDED, _context
from .llm import ATTEMPTS, EFFORT, MAX_TOKENS, Failed, prompt

set_tracing_disabled(True)  # nothing of a chat leaves through the SDK's tracing

MAX_ANSWER_CHARS = 600
MAX_TITLE_CHARS = 60
MAX_LINKS = 4
MAX_TOOL_CALLS = 8  # per message: past them, it answers with what it has
CALLS_LISTED = 30  # the latest, one line each
CALLS_IN_FULL = 3  # of those the chat names
CHAT_SHOWN = 8  # messages of the chat so far, the latest
LINK_KINDS = ("issue", "pull", "call")

_TEXT = {"type": "string"}
ANSWER = _object(
    answer=_TEXT,
    links=_list(
        _object(kind={"type": "string", "enum": list(LINK_KINDS)}, number={"type": "integer"})
    ),
)
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

    def spec(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": self.about,
            "parameters": self.params,
            "strict": True,
        }


def answer(agent_id: str, chat_id: int, about: tuple[dict, str], tools: dict[str, Tool]) -> dict:
    """Answer the chat's last message, about the copy `about` (from `copy_of`).

    Returns the chat with Prosper AI's message added: its answer, or the
    action it proposes. A model that gives no answer that passes its check
    is said in the chat, as Prosper AI's message.
    """
    chat = store.chats.get_chat(agent_id, chat_id)
    copy, name = about
    llm = setup.new_llm()
    facts = _facts(agent_id, copy, name, chat["messages"])
    start = [{"role": "user", "content": facts}]
    message = asyncio.run(_converse(_agent(tools, llm), llm, name, start, _scope(agent_id)))
    return store.chats.add_message(agent_id, chat_id, message, llm.usage)


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
    llm = setup.new_llm()
    follow = None
    try:
        follow = asyncio.run(_resume(_agent(tools, llm), llm, message["about"], saved, scope))
    except Exception:  # noqa: BLE001 - what was done is done; the rest is a nicety
        logger.exception("Ask Prosper AI · could not go on after an action")
    if not scope["settled"]:
        _settle(scope, None, "It could not be done: the conversation could not be picked up.")
    if follow is None:
        return store.chats.get_chat(agent_id, chat_id)
    return store.chats.add_message(agent_id, chat_id, follow, llm.usage)


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


class _Answer(AgentOutputSchemaBase):
    """The answer's JSON schema, ANSWER, as the SDK takes an output type."""

    def is_plain_text(self) -> bool:
        return False

    def name(self) -> str:
        return "ask"

    def json_schema(self) -> dict:
        return ANSWER

    def is_strict_json_schema(self) -> bool:
        return True

    def validate_json(self, json_str: str) -> dict:
        return json.loads(json_str)


def _agent(tools: dict[str, Tool], llm) -> Agent:
    return Agent(
        name=PROSPER,
        instructions=prompt("ask"),
        model=llm.agent_model(),
        model_settings=_SETTINGS,
        tools=[_function(tool) for tool in tools.values()],
        output_type=_Answer(),
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
    """Every request of a run counted and priced on `llm`, and logged with its time."""

    def __init__(self, llm):
        self.llm = llm
        self.started = 0.0

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.started = time.monotonic()

    async def on_llm_end(self, context, agent, response) -> None:
        self.llm.count(response.usage)
        calls = [item.name for item in response.output if item.type == "function_call"]
        did = f"calls {calls[0]}" if calls else "answers"
        logger.info(f"Prosper AI · ask · {did} · {time.monotonic() - self.started:.1f}s")


async def _resume(agent: Agent, llm, name: str, saved: dict, scope: dict) -> Optional[dict]:
    """Pick up the run kept with a card, its act approved: the act runs, then the run goes on."""
    state = await RunState.from_json(agent, saved, context_override=scope)
    for pending in state.get_interruptions():
        state.approve(pending)
    return await _converse(agent, llm, name, state, scope, after_action=True)


async def _converse(
    agent: Agent, llm, name: str, start, scope: dict, after_action: bool = False
) -> Optional[dict]:
    """Run the agent from `start` (the facts, or a run picked up) until it answers or proposes
    an act: its message.

    At most MAX_TOOL_CALLS tool calls, then it answers with what it has.
    After an action, Prosper AI may have nothing to add: then None.
    """
    hooks = _Counted(llm)
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
            said = result.final_output
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


def copy_of(agent_id: str, pull: Optional[int]) -> tuple[dict, str]:
    """The copy the person is looking at, and its name: live ("v2"), or "PR #5".

    Before the agent is live, its PR #1. Raises NotFound: resolved before the
    question is stored, so a question about nothing leaves nothing behind.
    """
    agent = store.get_agent(agent_id)
    if agent is None:
        raise store.NotFound(f"No agent with id '{agent_id}'.")
    if pull is None and agent["live_version"]:
        version = store.get_version(agent_id, agent["live_version"])
        return {**version, "pull": None}, f"v{version['number']}"
    if pull is None:
        open_ = store.list_pulls(agent_id, state="open")
        pull = next((p["number"] for p in open_ if p["kind"] == "setup"), None)
    found = store.get_pull(agent_id, pull) if pull is not None else None
    if found is None:
        raise store.NotFound(f"The agent has no {store.label(pull or 0)}.")
    return {**found, "pull": found["number"], "version": None}, store.label(found["number"])


def _when(at: Optional[str]) -> str:
    """A stored time as the person reads it: in the server's time zone, the clinic's."""
    if not at:
        return "never"
    return datetime.fromisoformat(at).astimezone().strftime("%a %d %b %H:%M")


def _facts(agent_id: str, copy: dict, name: str, messages: list[dict]) -> str:
    agent = store.get_agent(agent_id)
    now = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M")
    live = f"v{agent['live_version']}" if agent["live_version"] else "nothing yet"
    about = f"live, {name}" if copy["pull"] is None else f"{name}, a pull request not merged yet"
    calls = store.calls.list_calls(agent_id)
    parts = [
        f"Now: {now}. Live: {live}. The person is looking at {about}.",
        _context(agent_id, copy, name),
        tests_of(agent_id, copy, name),
        versions_of(agent_id),
        _pulls(agent_id),
        _issues(agent_id),
        _calls(calls),
        _in_full(agent_id, calls, messages),
        _chat(messages),
    ]
    return "\n\n".join(part for part in parts if part)


def tests_of(agent_id: str, copy: dict, name: str) -> str:
    if copy["pull"] is not None:
        run = store.get_run(agent_id, pull=copy["pull"])
    else:
        run = store.get_run(agent_id, version=copy["number"])
    results = {test["id"]: test for test in (run or {}).get("tests", [])}
    repeats = (run or {}).get("repeats", REPEATS)
    lines = []
    for test in copy["tests"]:
        result = results.get(test["id"])
        if result is None or not result["runs"]:
            how = "not run yet"
        else:
            passed = sum(1 for r in result["runs"] if r["passed"])
            how = f"{verdict(result, repeats)}, {passed}/{len(result['runs'])}"
            failed = [c for r in result["runs"] for c in r["checks"] if not c["pass"]]
            if failed:
                how += f' · failed "{failed[0]["text"]}": {failed[0]["detail"]}'
        lines.append(
            f"- {test['name']} · {how}\n  caller: {test['caller']}\n"
            f"  checks: {'; '.join(test['checks'])}"
        )
    ran = f"last run {_when(run['started_at'])}" if run else "never run"
    rule = (
        f"A test passes at {repeats}/{repeats}, is flaky one short of it (shown, and does not "
        "block a merge), and is failing below that (blocks a merge)."
    )
    head = f"Its tests on {name} ({ran}, {repeats} calls each). {rule}"
    if (summary := store.runs.summary(run)) and summary["state"] != "running":
        head += f" Now: {tally(summary)}."
    return f"{head}\n" + ("\n".join(lines) or "(none)")


def versions_of(agent_id: str) -> str:
    lines = [
        f"- v{v['number']}, {_when(v['created_at'])}"
        + (f', from PR #{v["pull"]} "{v["title"]}"' if v["pull"] else "")
        for v in store.list_versions(agent_id)
    ]
    return "Versions, live first:\n" + ("\n".join(lines) or "(none)")


def _pulls(agent_id: str) -> str:
    lines = [pull_line(pull) for pull in store.list_pulls(agent_id)]
    return "Pull requests, newest first:\n" + ("\n".join(lines) or "(none)")


def pull_line(pull: dict) -> str:
    """A pull request in a line: number, title, kind, why, state and checks."""
    state = f"merged as v{pull['merged_version']}" if pull["state"] == "merged" else pull["state"]
    checks = pull["checks"]
    if pull["state"] == "open" and checks:
        state += f", checks {checks['state']}: {tally(checks)}"
    why = f", fixes Issue #{pull['fixes']}" if pull["fixes"] else ""
    if pull["chat"]:
        why = f', asked for in the chat "{pull["chat"]["title"]}"'
    return (
        f'- PR #{pull["number"]} "{pull["title"]}" · {pull["kind"]}{why} · {state} · '
        f"opened {_when(pull['created_at'])}"
    )


def _issues(agent_id: str) -> str:
    lines = [issue_line(issue) for issue in store.issues.list_issues(agent_id)]
    return "Issues, newest first:\n" + ("\n".join(lines) or "(none)")


def tally(checks: dict) -> str:
    """How a copy's tests went, by the 2/3 rule: "8 pass, 2 flaky (no block), 1 failing"."""
    parts = [f"{checks['passed']} of {checks['total']} pass"]
    if checks["flaky"]:
        parts.append(f"{checks['flaky']} flaky (2/3: does not block a merge)")
    if checks["failing"]:
        parts.append(f"{checks['failing']} failing (blocks a merge)")
    return ", ".join(parts)


def issue_line(issue: dict) -> str:
    """An issue in two lines: number, state, who found it, severity, step, calls; its words."""
    fixed = f", fixed by PR #{issue['fixed']['pull']}" if issue["fixed"] else ""
    who = {"you": "reported by the team", "clinic": "flagged by the clinic"}.get(
        issue["reported"] or "", "found in calls"
    )
    last = f", last {_when(issue['last_seen'])}" if issue["last_seen"] else ""
    return (
        f"- Issue #{issue['number']} · {issue['state']}{fixed} · {who} · "
        f"{issue['severity'] or 'severity not set'} · step {issue['step'] or 'not known'} · "
        f"{issue['calls']} calls{last}\n"
        f"  {issue['title']}. {issue['description']}"
    )


def _tally(calls: list[dict]) -> str:
    """How many calls, and how they went, all of them and today's: what a count is asked of."""
    today = datetime.now().astimezone().date()

    def line(which: list[dict], name: str) -> str:
        if not which:
            return f"{name}: none."
        versions = Counter(f"v{call['version']}" for call in which)
        outcomes = Counter(call["outcome"] or "not reviewed" for call in which)
        flagged = sum(1 for call in which if call["issues"])
        return (
            f"{name}: {len(which)} calls ({', '.join(f'{n} on {v}' for v, n in versions.items())}),"
            f" {flagged} with an issue; outcomes: "
            + ", ".join(f"{n} {outcome}" for outcome, n in outcomes.most_common())
            + "."
        )

    on_day = [c for c in calls if datetime.fromisoformat(c["at"]).astimezone().date() == today]
    return f"{line(calls, 'All calls')}\n{line(on_day, 'Today')}"


def _calls(calls: list[dict]) -> str:
    if not calls:
        return "Calls: none yet."
    lines = [call_line(call) for call in calls[:CALLS_LISTED]]
    shown = f"the latest {len(lines)} of {len(calls)}" if len(calls) > len(lines) else "all"
    return f"{_tally(calls)}\n\nCalls, latest first ({shown}):\n" + "\n".join(lines)


def call_line(call: dict) -> str:
    """A call in a line: id, caller, when, version, length, outcome, how it ended, its issues."""
    issues = ", ".join(f"Issue #{n}" for n in call["issues"]) or "no issue"
    outcome = call["outcome"] or f"review {call['review']}"
    return (
        f"- call {call['id']} · {call['caller']} · {_when(call['at'])} · v{call['version']}"
        f" · {call['seconds']}s · {outcome} · {_ENDED.get(call['ended'], call['ended'])}"
        f" · {issues}"
    )


def _named(calls: list[dict], text: str) -> list[int]:
    """The calls `text` names: "call 12", or a caller's first or last name."""
    low = text.lower()
    ids = [int(n) for n in re.findall(r"\bcall\s*#?(\d+)", low)]
    for call in calls:
        names = [part for part in re.split(r"\W+", call["caller"].lower()) if len(part) > 2]
        if any(re.search(rf"\b{re.escape(part)}\b", low) for part in names):
            ids.append(call["id"])
    return list(dict.fromkeys(ids))


def _in_full(agent_id: str, calls: list[dict], messages: list[dict]) -> str:
    """The calls the chat is about, whole: the latest question first, then what came before."""
    wanted: list[int] = []
    for message in reversed(messages[-CHAT_SHOWN:]):
        wanted += _named(calls, message["text"])
        wanted += [link["number"] for link in message.get("links", []) if link["kind"] == "call"]
    shown = []
    for call_id in list(dict.fromkeys(wanted))[:CALLS_IN_FULL]:
        call = store.calls.get_call(agent_id, call_id)
        if call is not None:
            shown.append(call_in_full(call))
    return "The calls this chat is about, in full:\n\n" + "\n\n".join(shown) if shown else ""


def call_in_full(call: dict) -> str:
    """A call whole: who called, its path, what it recorded, what it failed, its transcript."""
    path = " > ".join(step["node"] for step in call["path"]) or "nowhere"
    collected = {k: v for step in call["path"] for k, v in (step["collected"] or {}).items()}
    lines = "\n".join(
        f"  [{i}] {line['role']}: {line['text']}" for i, line in enumerate(call["transcript"])
    )
    failed = "; ".join(c["text"] for c in call["checks"] if not c["passed"]) or "none"
    found = "\n".join(
        f"  - Issue #{f['issue']}, turn {f['turn']}: {f['why']}" for f in call["findings"]
    )
    return (
        f"call {call['id']} · {call['caller']} · {_when(call['at'])} · v{call['version']}\n"
        f"  who they were: {call['situation']}\n  path: {path}\n"
        f"  recorded: {collected or 'nothing'}\n  checks it failed: {failed}\n"
        f"{found + chr(10) if found else ''}{lines}"
    )


def _chat(messages: list[dict]) -> str:
    earlier = messages[:-1][-CHAT_SHOWN:]
    said = "\n".join(
        f"{'You' if m['by'] == PROSPER else 'They'}: {m['text']}{_did(m)}".rstrip() for m in earlier
    )
    chat = f"The chat so far:\n{said}\n\n" if said else ""
    return f"{chat}Their question: {messages[-1]['text']}"


def _did(message: dict) -> str:
    """What a message of Prosper AI's proposed, and what came of it, for the chat so far."""
    if message.get("offer"):
        return f" [offered a pull request: {message['offer']['title']}]"
    action = message.get("action")
    if not action:
        return ""
    proposed = " · ".join(
        part
        for part in (action["title"], action["what"], *action["meta"], *action.get("warnings", []))
        if part
    )
    outcome = {
        "done": (action.get("result") or {}).get("text", "done"),
        "failed": f"refused: {action.get('error')}",
        "declined": "they declined it, nothing was done",
        "skipped": "not done: they wrote again instead",
        "pending": "waiting for them",
        "running": "being done",
    }[action["state"]]
    return f" [proposed: {proposed} → {outcome}]"
