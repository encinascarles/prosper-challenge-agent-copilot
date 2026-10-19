#
# Ask Prosper AI: questions about an agent, answered in a chat, outside any
# pull request ("Can Anna book for a child?", "Why did Maria's call go to the
# nurse?", "How many calls failed this morning?").
#
# One request per answer, through llm.py like everything Prosper AI writes,
# with the facts about this agent written into it: the guidelines, the copy
# the person is looking at (live, or the pull request they are on) with its
# rules, its tests and how they last went, the versions, pull requests and
# issues, how many calls there were and how they went (all, and today's),
# and the latest calls, one line each. A call the chat names (by its
# caller or its number) is given whole: its transcript, its path and what
# Prosper AI found in it. That is what fits: a few dozen calls in a line each,
# and the few the question is about in full. No retrieval or tool calls: the
# facts of one agent fit in one prompt, and one request answers in seconds.
#
# The answer is checked in code like any artifact: short, steps named as
# words, and every issue, pull request or call it links to one that exists.
#
# A chat never changes the agent. Asked for a change, Prosper AI answers with
# an offer: a title and what it would change. Taking it opens a pull request
# of kind "change", where Prosper AI works as it does on a fix (fix.py): a
# test of what was asked first, then the smallest change, then the suite.
#

import re
from collections import Counter
from datetime import datetime
from typing import Optional

import store
from simulate.suite import REPEATS
from store.prosper import PROSPER
from store.runs import verdict

from . import setup
from .artifacts import _list, _object
from .calls import _ENDED, _context
from .llm import Failed

MAX_ANSWER_CHARS = 600
MAX_TITLE_CHARS = 60
MAX_LINKS = 4
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
    offer=_list(_object(title=_TEXT, what=_TEXT)),
)
# A name as the store keeps it, snake_case: never what a person reads.
_STORED_NAME = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


def answer(agent_id: str, chat_id: int, about: tuple[dict, str]) -> dict:
    """Answer the chat's last question, about the copy `about` (from `copy_of`).

    Returns the chat with the answer added. A model that gives no answer
    that passes its check is said in the chat, as Prosper AI's message.
    """
    chat = store.chats.get_chat(agent_id, chat_id)
    copy, name = about
    llm = setup.new_llm()
    facts = _facts(agent_id, copy, name, chat["messages"])
    try:
        said = llm.ask("ask", facts, ANSWER, lambda a: check_answer(a, _known(agent_id)))
        message = {
            "by": PROSPER,
            "text": said["answer"],
            "about": name,
            "links": _unique(said["links"]),
            **({"offer": {**said["offer"][0], "pull": None}} if said["offer"] else {}),
        }
    except Failed as error:
        message = {
            "by": PROSPER,
            "text": f"I couldn't answer that: {error} Ask me again.",
            "about": name,
            "failed": True,
        }
    return store.chats.add_message(agent_id, chat_id, message, llm.usage)


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
    if len(answer["offer"]) > 1:
        raise ValueError("Offer one pull request at most: the change asked for.")
    for offer in answer["offer"]:
        if not offer["title"].strip() or len(offer["title"]) > MAX_TITLE_CHARS:
            raise ValueError(
                f"The offer's title is one line of at most {MAX_TITLE_CHARS} characters."
            )
        if _STORED_NAME.search(offer["title"] + " " + offer["what"]):
            raise ValueError("Name steps and fields as words in the offer too.")


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
        _tests(agent_id, copy, name),
        _versions(agent_id),
        _pulls(agent_id),
        _issues(agent_id),
        _calls(calls),
        _in_full(agent_id, calls, messages),
        _chat(messages),
    ]
    return "\n\n".join(part for part in parts if part)


def _tests(agent_id: str, copy: dict, name: str) -> str:
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
    return f"Its tests on {name} ({ran}, {repeats} calls each):\n" + ("\n".join(lines) or "(none)")


def _versions(agent_id: str) -> str:
    lines = [
        f"- v{v['number']}, {_when(v['created_at'])}"
        + (f', from PR #{v["pull"]} "{v["title"]}"' if v["pull"] else "")
        for v in store.list_versions(agent_id)
    ]
    return "Versions, live first:\n" + ("\n".join(lines) or "(none)")


def _pulls(agent_id: str) -> str:
    lines = []
    for pull in store.list_pulls(agent_id):
        state = (
            f"merged as v{pull['merged_version']}" if pull["state"] == "merged" else pull["state"]
        )
        checks = pull["checks"]
        if pull["state"] == "open" and checks:
            state += f", checks {checks['state']} ({checks['passed']}/{checks['total']} pass)"
        why = f", fixes Issue #{pull['fixes']}" if pull["fixes"] else ""
        if pull["chat"]:
            why = f', asked for in the chat "{pull["chat"]["title"]}"'
        lines.append(
            f'- PR #{pull["number"]} "{pull["title"]}" · {pull["kind"]}{why} · {state} · '
            f"opened {_when(pull['created_at'])}"
        )
    return "Pull requests, newest first:\n" + ("\n".join(lines) or "(none)")


def _issues(agent_id: str) -> str:
    lines = []
    for issue in store.issues.list_issues(agent_id):
        fixed = f", fixed by PR #{issue['fixed']['pull']}" if issue["fixed"] else ""
        who = {"you": "reported by the team", "clinic": "flagged by the clinic"}.get(
            issue["reported"] or "", "found in calls"
        )
        last = f", last {_when(issue['last_seen'])}" if issue["last_seen"] else ""
        lines.append(
            f"- Issue #{issue['number']} · {issue['state']}{fixed} · {who} · "
            f"{issue['severity'] or 'severity not set'} · step {issue['step'] or 'not known'} · "
            f"{issue['calls']} calls{last}\n"
            f"  {issue['title']}. {issue['description']}"
        )
    return "Issues, newest first:\n" + ("\n".join(lines) or "(none)")


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
    lines = []
    for call in calls[:CALLS_LISTED]:
        issues = ", ".join(f"Issue #{n}" for n in call["issues"]) or "no issue"
        outcome = call["outcome"] or f"review {call['review']}"
        lines.append(
            f"- call {call['id']} · {call['caller']} · {_when(call['at'])} · v{call['version']}"
            f" · {call['seconds']}s · {outcome} · {_ENDED.get(call['ended'], call['ended'])}"
            f" · {issues}"
        )
    shown = f"the latest {len(lines)} of {len(calls)}" if len(calls) > len(lines) else "all"
    return f"{_tally(calls)}\n\nCalls, latest first ({shown}):\n" + "\n".join(lines)


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
        if call is None:
            continue
        path = " > ".join(step["node"] for step in call["path"]) or "nowhere"
        collected = {k: v for step in call["path"] for k, v in (step["collected"] or {}).items()}
        lines = "\n".join(
            f"  [{i}] {line['role']}: {line['text']}" for i, line in enumerate(call["transcript"])
        )
        failed = "; ".join(c["text"] for c in call["checks"] if not c["passed"]) or "none"
        found = "\n".join(
            f"  - Issue #{f['issue']}, turn {f['turn']}: {f['why']}" for f in call["findings"]
        )
        shown.append(
            f"call {call['id']} · {call['caller']} · {_when(call['at'])} · v{call['version']}\n"
            f"  who they were: {call['situation']}\n  path: {path}\n"
            f"  recorded: {collected or 'nothing'}\n  checks it failed: {failed}\n"
            f"{found + chr(10) if found else ''}{lines}"
        )
    return "The calls this chat is about, in full:\n\n" + "\n\n".join(shown) if shown else ""


def _chat(messages: list[dict]) -> str:
    earlier = messages[:-1][-CHAT_SHOWN:]
    said = "\n".join(
        f"{'You' if m['by'] == PROSPER else 'They'}: {m['text']}"
        + (f" [offered a pull request: {m['offer']['title']}]" if m.get("offer") else "")
        for m in earlier
    )
    chat = f"The chat so far:\n{said}\n\n" if said else ""
    return f"{chat}Their question: {messages[-1]['text']}"
