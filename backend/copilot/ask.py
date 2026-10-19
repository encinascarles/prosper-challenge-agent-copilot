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
# Then tools (api/tools.py), through llm.turn, one call per step and at most
# MAX_TOOL_CALLS per message. A tool that reads (search calls, read an issue,
# read a pull request's tests) runs at once and its result goes back to the
# model; the chat shows a muted line for it ("Read Issue #5 and its 3
# calls"). A tool that acts never runs from here: the message ends with its
# card ("Open issue: Books under the parent's name · Collect details ·
# Booking"), and the conversation so far is kept on the message. When the
# person clicks Do it, the tool runs (`decide`), the card says what happened,
# and the conversation goes on from there with the result, so Prosper AI can
# say what is next or propose the next step. Cancel only marks the card:
# the next question tells Prosper AI it was declined. Nothing changes from a
# chat without a click.
#
# Each tool is a route the UI calls, called as a function: the same checks,
# and the same 404/409/422 sentences, which go back to the model as the
# tool's refusal for it to correct or explain.
#
# The final answer is checked in code like any artifact: short, steps named
# as words, and every issue, pull request or call it links to one that exists.
#

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from loguru import logger

import store
from simulate.suite import REPEATS
from store.prosper import PROSPER
from store.runs import verdict

from . import setup
from .artifacts import _list, _object
from .calls import _ENDED, _context
from .llm import ATTEMPTS, Failed

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
    # An act: its card, { title, what, meta }, made before anything is done;
    # it raises ToolError when the act would be refused, so the model hears it
    # before the person does.
    card: Optional[Callable[[str, dict], dict]] = None
    # And doing it, once the person says so: (agent id, arguments, { chat,
    # message }) -> { text, link, said }: what the card then says, what it
    # links to, and what the model is told.
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
    message = _converse(agent_id, name, tools, llm, [{"role": "user", "content": facts}], 0)
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
    done, error = None, None
    try:
        done = tools[action["tool"]].act(
            agent_id, action["args"], {"chat": chat_id, "message": index}
        )
    except ToolError as refused:
        error = str(refused)
    except Exception as failure:  # noqa: BLE001 - the card must not stay "running"
        logger.exception(f"Ask Prosper AI · {action['tool']} failed")
        error = f"It could not be done: {failure}"
    result = {"text": done["text"], "link": done.get("link")} if done else None
    chat = store.chats.settle_action(agent_id, chat_id, index, result, error)
    resume = message.get("resume")
    if resume is None:
        return chat
    output = done["said"] if done else f"Refused: {error}"
    items = [*resume["items"], _output(resume["call"], output)]
    llm = setup.new_llm()
    try:
        follow = _converse(agent_id, message["about"], tools, llm, items, resume["used"], True)
    except Exception:  # noqa: BLE001 - what was done is done; the rest is a nicety
        logger.exception("Ask Prosper AI · could not go on after an action")
        follow = None
    if follow is None:
        return chat
    return store.chats.add_message(agent_id, chat_id, follow, llm.usage)


def _output(call_id: str, text: str) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def _converse(
    agent_id: str,
    name: str,
    tools: dict[str, Tool],
    llm,
    items: list,
    used: int,
    after_action: bool = False,
) -> Optional[dict]:
    """Talk with the model from `items` until it answers or proposes an act: its message.

    `used`: tool calls this message made already. After an action, Prosper
    AI may have nothing to add: then None.
    """
    specs = [tool.spec() for tool in tools.values()]
    reads: list[str] = []
    base = {"by": PROSPER, "about": name, "links": [], "reads": reads}
    refused = 0
    try:
        while True:
            step = llm.turn("ask", items, specs, ANSWER, use_tools=used < MAX_TOOL_CALLS)
            items = [*items, *step["output"]]
            call = step["call"]
            if call is None:
                try:
                    said = json.loads(step["text"])
                    if after_action and not said["answer"].strip():
                        return None
                    check_answer(said, _known(agent_id))
                except ValueError as error:
                    refused += 1
                    if refused >= ATTEMPTS:
                        raise Failed(str(error)) from error
                    items.append(
                        {
                            "role": "user",
                            "content": f"That was refused: {error}\n"
                            "Fix it and answer again with the whole JSON.",
                        }
                    )
                    continue
                return {**base, "text": said["answer"], "links": _unique(said["links"])}
            used += 1
            tool = tools.get(call["name"])
            try:
                if tool is None:
                    raise ToolError(f"There is no tool {call['name']}.")
                args = json.loads(call["arguments"])
                if tool.read is not None:
                    output, line = tool.read(agent_id, args)
                    reads.append(line)
                else:
                    action = {"tool": tool.name, "args": args, **tool.card(agent_id, args)}
                    resume = {"items": items, "call": call["call_id"], "used": used}
                    return {
                        **base,
                        "text": "",
                        "action": {**action, "state": "pending"},
                        "resume": resume,
                    }
            except ToolError as error:
                output = f"Refused: {error}"
            items.append(_output(call["call_id"], output))
    except Failed as error:
        return {**base, "text": f"I couldn't answer that: {error} Ask me again.", "failed": True}


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
        part for part in (action["title"], action["what"], *action["meta"]) if part
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
