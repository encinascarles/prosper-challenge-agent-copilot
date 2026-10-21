#
# What Prosper AI reads first, as plain lines: the facts a chat's answer
# starts from (the agent, its tests and how they went, versions, pull
# requests, issues and calls), and the lines its reads answer with. Never
# JSON for what is about calls or issues: shorter, and what the model reads
# best. The agent itself is given in the shape Prosper AI edits it in.
#

import json
import re
from collections import Counter
from datetime import datetime
from typing import Optional

import store
from simulate.suite import REPEATS
from store.prosper import PROSPER
from store.runs import verdict

from . import artifacts
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


# ---- at work on a pull request ------------------------------------------------

CALLS_SHOWN = 3  # of an issue's calls, the latest, given to write its test from
LINES_BEFORE = 10  # of each, the lines before the turn that went wrong
EVENTS_SHOWN = 40  # of a pull request's conversation, the latest
_REPORTERS = {"you": "the deployment team", "clinic": "the clinic"}


def words(name: Optional[str]) -> str:
    # A step as the editor shows it: "offer_times" is "Offer times".
    return (name or "").replace("_", " ").capitalize()


def callers(issue: dict) -> str:
    names = list(dict.fromkeys(found["caller"] for found in issue["findings"]))
    if not names:
        return "calls like the one reported"
    if len(names) == 1:
        return f"calls like {names[0]}"
    return f"calls like these {len(names)} callers"


def the_call(result: dict, whole: bool = False) -> str:
    """A test's call as Prosper AI reads it: what failed, the path, the last lines (or all)."""
    failed = "; ".join(f"{c['text']} ({c['detail']})" for c in result["checks"] if not c["pass"])
    path = " > ".join(step["node"] for step in result["path"]) or "nowhere"
    shown = result["transcript"] if whole else result["transcript"][-14:]
    lines = "\n".join(f"  {line['role']}: {line['text']}" for line in shown)
    return f"  failed: {failed or 'nothing'}\n  path: {path} · ended: {result['ended']}\n{lines}"


def issue_about(issue: dict) -> str:
    severity = f" ({issue['severity']})" if issue["severity"] else ""
    if issue["reported"]:
        where = f"in step {issue['step']}" if issue["step"] else "step not known"
        return (
            f"Issue #{issue['number']}{severity}, reported by {_REPORTERS[issue['reported']]} "
            f"({where}): {issue['title']}.\nWhat they said happened: {issue['description']}"
        )
    return (
        f"Issue #{issue['number']}{severity}, first seen in step {issue['step']}: "
        f"{issue['title']}. {issue['description']}"
    )


def issue_calls(agent_id: str, issue: dict) -> str:
    """The issue's latest calls as a test writer reads them: who called, up to the bad turn.

    A call a person linked has no bad turn: it is given whole. With no calls
    at all, the test is written from what the person said happened.
    """
    shown = []
    for found in issue["findings"][:CALLS_SHOWN]:
        call = store.calls.get_call(agent_id, found["call"])
        if call is None:
            continue
        linked = found["turn"] < 0
        end = len(call["transcript"]) if linked else found["turn"] + 1
        start = 0 if linked else max(0, end - 1 - LINES_BEFORE)
        lines = "\n".join(
            f"  [{i}] {line['role']}: {line['text']}"
            for i, line in enumerate(call["transcript"][start:end], start)
        )
        where = (
            "Linked by the person who reported it: the whole call."
            if linked
            else f'It went wrong on turn {found["turn"]} ("{found["quote"]}"): {found["why"]}'
        )
        shown.append(
            f"- {call['caller']}, on v{call['version']}. Who they were: {call['situation']}\n"
            f"  {where}\n{lines}"
        )
    if not shown:
        return (
            "It has no calls: write the caller from what was reported, the situation it "
            "describes and what the caller says when it goes wrong."
        )
    return f"Its calls ({issue['calls']} in all, the latest {len(shown)} here):\n" + "\n\n".join(
        shown
    )


def _guidelines(agent_id: str, pull: dict) -> tuple[str, str]:
    """The guidelines and the clinic's answers: the setup's own, or what the agent was built
    from, with what was answered in this pull request."""
    work = store.prosper.work_of(agent_id, pull["number"])
    sources, answered = store.prosper.guidelines(agent_id)
    if pull["kind"] == "setup":
        sources, answered = work.get("sources", []), []
    answered = answered + [q for q in work.get("questions", []) if q["answer"]]
    if sources:
        names = ", ".join(f'"{source["name"]}"' for source in sources)
        texts = "\n\n".join(f"=== {s['name']} ===\n{s['text']}" for s in sources)
        guidelines = f"The guidelines, from {len(sources)} sources: {names}.\n\n{texts}"
    else:
        guidelines = "No written guidelines: the agent's steps and rules are what the clinic asked."
    given = "\n".join(f'- "{q["text"]}" → "{q["answer"]}"' for q in answered) or "(none)"
    return guidelines, given


_KINDS = {
    "setup": "the setup of a new agent, from the clinic's guidelines",
    "fix": "a fix of Issue #{fixes}, on v{base_version}",
    "change": "a change asked for in a chat, on v{base_version}",
    "edit": "the person's own changes, on v{base_version}",
}


def _rule_line(rule: dict) -> str:
    quote = (rule.get("source") or {}).get("quote")
    said = f' (quotes: "{quote}")' if quote else ""
    return f"- [{rule['id']}] {words(rule['step']) or 'every step'}: {rule['text']}{said}"


def _event_line(event: dict) -> Optional[str]:
    who = "They" if event["by"] == "you" else event["by"]
    kind = event["type"]
    if kind == "checks":
        return f"- Checks: {event['passed']} of {event['total']} pass, {event['flaky']} flaky"
    if kind in ("rule", "test"):
        verb = (
            "took out" if event.get("removed") else "rewrote" if event.get("rewritten") else "added"
        )
        return f"- {who} {verb} a {kind}: {event.get('text')}"
    if kind == "question":
        return f"- {who} asked: {event['text']} Options: {' / '.join(event['options'])}"
    if kind == "answer":
        return f"- They answered: {event['text']}"
    if kind in ("request", "message", "step", "reproduced", "proposed", "proved"):
        details = "".join(f"\n    {line}" for line in event.get("details") or [])
        return f"- {who}: {event.get('text') or ''}{details}"
    if kind in ("saved", "updated", "merged", "closed", "reopened", "interrupted"):
        return f"- {who} {kind} it" + (f": {event['summary']}" if event.get("summary") else "")
    return None


def at_work(agent_id: str, pull: dict, said: Optional[str]) -> str:
    """What a turn of Prosper AI's work on `pull` starts from: the guidelines, what it is for,
    the copy and how its tests went, where the work stands, the conversation, and what
    starts this turn (`said`: the person's message or answer; None to start or go on)."""
    from . import work as working  # it builds on this module

    record = store.prosper.work_of(agent_id, pull["number"])
    done = set(record.get("built", []))
    label = store.label(pull["number"])
    now = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M")
    what = _KINDS[pull["kind"]].format(**pull)
    guidelines, given = _guidelines(agent_id, pull)
    parts = [
        f'Now: {now}. You are working on {label} "{pull["title"]}": {what}. Nothing in it '
        "reaches callers until the person merges it.",
        guidelines,
        f"The clinic's answers to your questions:\n{given}",
    ]
    if subject := working.subject_of(agent_id, pull):
        if subject.issue:
            parts.append(f"What it fixes: {issue_about(subject.issue)}")
            parts.append(issue_calls(agent_id, subject.issue))
        else:
            parts.append(
                f'What it changes, as the person asked in a chat: "{subject.request["text"]}"'
                + (
                    f"\nAs you offered it: {subject.request['what']}"
                    if subject.request["what"]
                    else ""
                )
            )
    config = pull["config"]
    agent = (
        json.dumps(artifacts.from_config(config), indent=1)
        if config["nodes"]
        else "(nothing drawn yet)"
    )
    tests = "\n".join(
        f"- [{t['id']}] {t['name']}\n  caller: {t['caller']}\n  checks: {'; '.join(t['checks'])}"
        for t in pull["tests"]
    )
    parts += [
        f"The agent in {label} (it has no calendar and no patient records):\n{agent}",
        "Its rules:\n" + ("\n".join(_rule_line(r) for r in pull["rules"]) or "(none)"),
        f"Its tests:\n{tests or '(none)'}",
        working.results(agent_id, pull),
    ]
    if pull["kind"] != "setup" and (flaky := working.flaky_on_base(agent_id, pull)):
        names = ", ".join(flaky.values())
        parts.append(f"Already flaky (2/3) on v{pull['base_version']}: {names}.")
    parts.append("Where the work stands:\n" + _standing(agent_id, pull, record, done))
    lines = [line for e in pull["events"][-EVENTS_SHOWN:] if (line := _event_line(e))]
    parts.append("The conversation so far, latest last:\n" + ("\n".join(lines) or "(nothing)"))
    if said is not None:
        parts.append(f"Their message: {said}")
    elif record.get("state") == "failed" or pull["events"][-1]["type"] == "interrupted":
        parts.append("You were stopped before you finished: go on from where the work stands.")
    else:
        parts.append("Start.")
    return "\n\n".join(parts)


def _standing(agent_id: str, pull: dict, record: dict, done: set) -> str:
    from . import work as working

    questions = record.get("questions", [])
    open_ = [q for q in questions if q["answer"] is None]
    lines = []
    if pull["kind"] == "setup":
        if "asked" not in done:
            lines.append("- You have not asked the clinic about the guidelines' gaps yet.")
        elif open_:
            lines.append("- Waiting for the clinic's answers.")
        else:
            lines.append("- Every question you asked has its answer.")
        lines.append(f"- Drawn: {'yes' if pull['config']['nodes'] else 'not yet'}.")
    if subject := working.subject_of(agent_id, pull):
        if "reproduced" in done:
            test = next((t for t in pull["tests"] if working.is_test_of(t, pull["number"])), None)
            before = (test or {}).get("source", {}).get("before") or {}
            lines.append(
                f'- Reproduced: "{(test or {}).get("name")}" passed {before.get("passed")}/'
                f"{before.get('runs')} on v{before.get('version')}"
                + (
                    "."
                    if before.get("runs", 0) - before.get("passed", 0) > 1
                    else ": it did not fail there; the person said to go on."
                )
            )
        else:
            left = subject.tries - record.get("tries", 0)
            lines.append(
                f"- Not reproduced yet: {max(left, 0)} tries left on v{pull['base_version']}."
            )
    return "\n".join(lines) or "- Nothing in particular: the conversation says what is asked."
