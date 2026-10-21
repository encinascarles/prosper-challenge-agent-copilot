#
# What Prosper AI reads first, as plain lines: the facts a chat's answer
# starts from (the agent, its tests and how they went, versions, pull
# requests, issues and calls), and the lines its reads answer with. Never
# JSON for what is about calls or issues: shorter, and what the model reads
# best. The agent itself is given in the shape Prosper AI edits it in.
#

import re
from collections import Counter
from datetime import datetime
from typing import Optional

import store
from simulate.suite import REPEATS
from store.prosper import PROSPER
from store.runs import verdict

from .calls import _ENDED, _context

CALLS_LISTED = 30  # the latest, one line each
CALLS_IN_FULL = 3  # of those the chat names
CHAT_SHOWN = 8  # messages of the chat so far, the latest


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


def when(at: Optional[str]) -> str:
    """A stored time as the person reads it: in the server's time zone, the clinic's."""
    if not at:
        return "never"
    return datetime.fromisoformat(at).astimezone().strftime("%a %d %b %H:%M")


def for_chat(agent_id: str, copy: dict, name: str, messages: list[dict]) -> str:
    """What a chat's answer starts from: the agent, its tests, versions, pull requests, issues
    and calls, the calls the chat names in full, and the chat so far."""
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
    ran = f"last run {when(run['started_at'])}" if run else "never run"
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
        f"- v{v['number']}, {when(v['created_at'])}"
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
        f"opened {when(pull['created_at'])}"
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
    last = f", last {when(issue['last_seen'])}" if issue["last_seen"] else ""
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
        f"- call {call['id']} · {call['caller']} · {when(call['at'])} · v{call['version']}"
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
        f"call {call['id']} · {call['caller']} · {when(call['at'])} · v{call['version']}\n"
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
