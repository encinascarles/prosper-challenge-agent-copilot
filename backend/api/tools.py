#
# Prosper AI's tools: what it reads, what it does once the person says so (in
# a chat), and how it works on a pull request's copy (in its conversation).
# copilot/agent.py runs them; this is what they are, one set for both.
#
# Each is a route the UI calls, called here as a function: an issue opened
# from a chat goes through report_issue like one from New issue, a merge
# through merge_pull like the Merge button. So there is one implementation of
# every action, with the same checks, and what a route refuses (404, 409, a
# 422, a body that fails validation) reaches Prosper AI as the tool's refusal
# in the words the person would read. Acts are done as "you": the person who
# clicked Do it.
#
# An act has a card, made before anything is done: what it will do, in the
# product's words, and what follows from it ("Merge PR #5 as v3 · calls will
# use v3"). The card is made from the same checks the act will meet where
# they can be asked without acting (the step exists, the pull request can
# merge), so a refusal goes back to Prosper AI at once instead of to the
# person after their click.
#
# Reads answer in plain lines, the same as the facts Prosper AI starts from,
# never JSON: shorter, and what the model reads best.
#
# Work on a pull request's copy runs at once, with no card: nothing there
# reaches callers before a person merges it. It comes in small pieces (draw a
# new agent whole, then one step's task, one way it moves on, one field, a
# rule, a test), each written to the copy through the store like the editor's
# saves, and each checked first as a save is (AgentBuilder) and as Prosper
# AI's writing is (artifacts.py): a task of three short sentences, a rule
# quoting its line word for word, a check naming a real step, the product's
# words. Where the work stands is checked too (copilot/work.py). What is
# refused goes back to the model in the sentence that says why.
#

import json
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

import store
from agent_builder.schema import DEFAULT_MODEL
from copilot import agent, artifacts, work
from copilot.agent import Tool, ToolError, Work
from copilot.facts import (
    call_in_full,
    call_line,
    copy_of,
    issue_line,
    pull_line,
    tests_of,
    the_call,
    versions_of,
)
from copilot.tidy import first_line
from simulate import REPEATS

from . import live, pulls, suite
from .models import problem

MAX_FOUND = 40  # calls a search lists

_INT = {"type": "integer"}
_TEXT = {"type": "string"}


def _maybe(schema: dict) -> dict:
    """`schema`, or null: an argument the model may leave out (strict mode has no optional)."""
    nullable = {**schema, "type": [schema["type"], "null"]}
    if "enum" in schema:
        nullable["enum"] = [*schema["enum"], None]
    return nullable


def _args(**properties) -> dict:
    return artifacts._object(**properties)


def _enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


def _call(route: Callable, *args) -> Any:
    """The route's answer, or ToolError with the sentence it refused with."""
    try:
        answer = route(*args)
    except HTTPException as error:
        raise ToolError(str(error.detail)) from error
    except (store.NotFound, store.Conflict) as error:
        raise ToolError(str(error)) from error
    if isinstance(answer, JSONResponse):
        raise ToolError(json.loads(answer.body)["detail"])
    return answer


def _body(model: type[BaseModel], **fields) -> BaseModel:
    """The route's body, validated as the route validates it."""
    try:
        return model(**fields)
    except ValidationError as error:
        said = [e["msg"].removeprefix("Value error, ") for e in error.errors()]
        raise ToolError(" ".join(said)) from error


def _words(name: Optional[str]) -> str:
    # A step as the person reads it: "offer_times" is "Offer times".
    return (name or "").replace("_", " ").capitalize()


def _live(agent_id: str) -> int:
    agent = _call(pulls._agent, agent_id)
    if not agent["live_version"]:
        raise ToolError("The agent is not live yet: it goes live when PR #1 merges.")
    return agent["live_version"]


def _copy(agent_id: str, pull: Optional[int]) -> tuple[dict, str]:
    """The copy a tool is about: the open pull request `pull`, or live."""
    if pull is not None:
        found = _call(pulls.get_pull, agent_id, pull)
        return {**found, "pull": pull, "version": None}, store.label(pull)
    return _call(copy_of, agent_id, None)


def _labels(numbers: list[int], kind: str = "Issue") -> str:
    labels = [f"{kind} #{n}" for n in numbers]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def _link(kind: str, number: int = 0) -> dict:
    return {"kind": kind, "number": number}


# --- Reads -------------------------------------------------------------------


def search_calls(agent_id: str, args: dict) -> tuple[str, str]:
    calls = _call(live.list_calls, agent_id)["calls"]
    said = []
    if who := (args["caller"] or "").strip().lower():
        calls = [c for c in calls if who in c["caller"].lower()]
        said.append(args["caller"].strip())
    if args["outcome"]:
        calls = [c for c in calls if c["outcome"] == args["outcome"]]
        said.append(args["outcome"].replace("_", " "))
    if args["issue"] is not None:
        calls = [c for c in calls if args["issue"] in c["issues"]]
        said.append(f"Issue #{args['issue']}")
    if args["version"] is not None:
        calls = [c for c in calls if c["version"] == args["version"]]
        said.append(f"v{args['version']}")
    if args["day"]:
        day = args["day"]
        calls = [c for c in calls if _day(c["at"]) == day]
        said.append(f"on {day}")
    lines = [call_line(call) for call in calls[:MAX_FOUND]]
    more = f"\n(and {len(calls) - MAX_FOUND} more, older)" if len(calls) > MAX_FOUND else ""
    found = f"{len(calls)} call{'s' if len(calls) != 1 else ''}"
    output = f"{found}, latest first:\n" + "\n".join(lines) + more if lines else "No calls found."
    return output, f"Found {found}" + (f" · {' · '.join(said)}" if said else "")


def _day(at: str) -> str:
    # The clinic's day: the server's time zone, as the facts give times.
    return datetime.fromisoformat(at).astimezone().date().isoformat()


def read_call(agent_id: str, args: dict) -> tuple[str, str]:
    call = _call(live.get_call, agent_id, args["call"])
    return call_in_full(call), f"Read {call['caller']}'s call"


def list_issues(agent_id: str, args: dict) -> tuple[str, str]:
    issues = _call(live.list_issues, agent_id)
    if args["state"]:
        issues = [i for i in issues if i["state"] == args["state"]]
    lines = "\n".join(issue_line(issue) for issue in issues) or "(none)"
    which = f"{args['state']} " if args["state"] else ""
    return lines, f"Listed {len(issues)} {which}issue{'s' if len(issues) != 1 else ''}"


def read_issue(agent_id: str, args: dict) -> tuple[str, str]:
    issue = _call(live.get_issue, agent_id, args["number"])
    events = "\n".join(
        f"- {_when(e['at'])} · {e['type']} by {e['by']}"
        + "".join(f" · {key} {e[key]}" for key in ("text", "pull", "version", "call") if e.get(key))
        for e in issue["events"]
    )
    calls = "\n".join(
        f"- call {f['call']} · {f['caller']} · v{f['version']} · {f['outcome'] or 'not reviewed'}"
        + (f'\n  turn {f["turn"]}: "{f["quote"]}" ({f["why"]})' if f["turn"] >= 0 else "")
        for f in issue["findings"]
    )
    fixes = "\n".join(f"- PR #{p['number']} {p['title']} · {p['state']}" for p in issue["pulls"])
    output = (
        f"{issue_line(issue)}\n\nIts calls, latest first:\n{calls or '(none)'}"
        f"\n\nPull requests fixing it:\n{fixes or '(none)'}\n\nWhat happened to it:\n{events}"
    )
    count = len(issue["findings"])
    return output, f"Read Issue #{issue['number']} and its {count} call{'s' if count != 1 else ''}"


def _when(at: str) -> str:
    return datetime.fromisoformat(at).astimezone().strftime("%a %d %b %H:%M")


def list_pulls(agent_id: str, args: dict) -> tuple[str, str]:
    found = _call(pulls.list_pulls, agent_id, args["state"])
    which = f"{args['state']} " if args["state"] else ""
    lines = "\n".join(pull_line(pull) for pull in found) or "(none)"
    return lines, f"Listed {len(found)} {which}pull request{'s' if len(found) != 1 else ''}"


# The events of a pull request's conversation that say what happened in it.
_TOLD = ("request", "step", "message", "question", "answer", "reproduced", "proposed", "proved")


def read_pull(agent_id: str, args: dict) -> tuple[str, str]:
    pull = _call(pulls.get_pull, agent_id, args["number"])
    added = [
        f"- rule, {_words(r['step']) or 'every step'}: {r['text']}"
        for r in pull["rules"]
        if r["source"].get("pull") == pull["number"]
    ] + [
        f'- test "{t["name"]}": {"; ".join(t["checks"])}'
        for t in pull["tests"]
        if t["source"].get("pull") == pull["number"]
    ]
    events = [
        f"- {e['by']}, {e['type']}: {e.get('text') or e.get('summary') or ''}".rstrip(": ")
        for e in pull["events"]
        if e["type"] in _TOLD or e["type"] in ("saved", "merged", "closed", "reopened", "checks")
    ][-20:]
    work = pull.get("prosper") or {}
    doing = f"\nProsper AI: {work['state']}, {work.get('doing') or ''}" if work else ""
    output = (
        f"{pull_line(pull)}{doing}\n\nRules and tests it adds:\n"
        f"{chr(10).join(added) or '(none)'}\n\nIts conversation, latest last:\n"
        f"{chr(10).join(events) or '(nothing)'}\n\nTo see its steps, read_agent with this pull."
    )
    return output, f"Read {store.label(pull['number'])}"


def read_tests(agent_id: str, args: dict) -> tuple[str, str]:
    copy, name = _copy(agent_id, args["pull"])
    return tests_of(agent_id, copy, name), f"Read the tests on {name} and how they last went"


def read_agent(agent_id: str, args: dict) -> tuple[str, str]:
    if args["version"] is not None:
        version = _call(pulls.get_version, agent_id, args["version"])
        copy, name = version, f"v{version['number']}"
    else:
        copy, name = _copy(agent_id, args["pull"])
    rules = "\n".join(f"- {_words(r['step']) or 'every step'}: {r['text']}" for r in copy["rules"])
    agent = json.dumps(artifacts.from_config(copy["config"]), indent=1)
    return f"{name}:\n{agent}\n\nIts rules:\n{rules or '(none)'}", f"Read the steps of {name}"


def list_versions(agent_id: str, args: dict) -> tuple[str, str]:
    _call(pulls._agent, agent_id)
    return versions_of(agent_id), "Read the versions"


# --- Acts --------------------------------------------------------------------


def _card(
    title: str,
    what: str = "",
    *meta: str,
    stored: Optional[list[str]] = None,
    warnings: Optional[list[str]] = None,
) -> dict:
    # `stored`: the words the act will keep (an issue's account, a test's
    # caller and checks), shown whole so the click is an informed one: they
    # may come from a call's transcript, which a caller wrote. `warnings`:
    # what a merge would be asked to confirm, said on the card instead.
    card = {"title": title, "what": what, "meta": [m for m in meta if m], "stored": stored or []}
    return {**card, "warnings": warnings} if warnings else card


MAX_STORED_CHARS = 400  # of an issue's account, on its card


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_STORED_CHARS else text[: MAX_STORED_CHARS - 1] + "…"


def _issue(agent_id: str, number: int) -> dict:
    return _call(live.get_issue, agent_id, number)


def _report(args: dict) -> BaseModel:
    return _body(
        live.IssueReport,
        title=args["title"],
        description=args["description"],
        step=args["step"] or "",
        severity=args["severity"],
        reported=args["reported"],
        calls=args["calls"],
    )


def open_issue_card(agent_id: str, args: dict) -> dict:
    report = _report(args)
    _call(store.issues.check_step, agent_id, report.step)
    known = {call["id"] for call in store.calls.list_calls(agent_id)}
    if missing := [n for n in report.calls if n not in known]:
        raise ToolError(f"The agent has no call {missing[0]}.")
    calls = len(report.calls)
    return _card(
        "Open issue",
        report.title or first_line(report.description),
        _words(report.step) or "Step not known",
        (report.severity or "severity not set").capitalize(),
        "Flagged by the clinic" if report.reported == "clinic" else "",
        f"{calls} call{'s' if calls != 1 else ''}" if calls else "",
        stored=[_clip(report.description)],
    )


def open_issue(agent_id: str, args: dict, at: dict) -> dict:
    issue = _call(live.report_issue, agent_id, _report(args))
    label = f"Issue #{issue['number']}"
    said = f'Opened {label}, "{issue["title"]}".'
    return {"text": f"Opened {label}", "link": _link("issue", issue["number"]), "said": said}


def tidy_issue_card(agent_id: str, args: dict) -> dict:
    issue = _issue(agent_id, args["number"])
    if issue["reported"] is None:
        raise ToolError(f"Issue #{issue['number']} was found in calls: it is tidy already.")
    return _card(
        f"Tidy Issue #{issue['number']}",
        issue["title"],
        "A plain title, its step and severity, and the calls that show it",
    )


def tidy_issue(agent_id: str, args: dict, at: dict) -> dict:
    number = args["number"]
    tidied = _call(live.tidy_issue, agent_id, number)
    edit = _body(
        live.IssueEdit,
        title=tidied["title"],
        step=tidied["step"],
        severity=tidied["severity"],
        calls=tidied["calls"],
        tidied=True,
    )
    issue = _call(live.edit_issue, agent_id, number, edit)
    said = (
        f'Tidied Issue #{number}: "{issue["title"]}", step {issue["step"] or "not known"}, '
        f"{issue['severity']}, {issue['calls']} calls."
    )
    return {"text": f"Tidied Issue #{number}", "link": _link("issue", number), "said": said}


def fix_issue_card(agent_id: str, args: dict) -> dict:
    version = _live(agent_id)
    issue = _call(store.issues.fixable, agent_id, args["number"])
    return _card(
        f"Fix Issue #{issue['number']} with Prosper AI",
        issue["title"],
        f"Opens a pull request on v{version}",
        "a test that shows it first, then the smallest change",
    )


def fix_issue(agent_id: str, args: dict, at: dict) -> dict:
    pull = _call(live.fix, agent_id, args["number"], live.Fix(prosper=True))
    label = store.label(pull["number"])
    said = (
        f"Opened {label}. Prosper AI works on it now: a test that reproduces the issue, the "
        "smallest change, then the whole suite. It takes a few minutes; read_pull follows it."
    )
    return {"text": f"Opened {label}", "link": _link("pull", pull["number"]), "said": said}


def open_pull_card(agent_id: str, args: dict) -> dict:
    version = _live(agent_id)
    if not args["title"].strip() or not args["what"].strip():
        raise ToolError("Give the pull request a title and say what it changes.")
    return _card(
        "Open a pull request",
        args["title"],
        args["what"],
        f"On v{version} · nothing goes live until you merge",
    )


def open_pull(agent_id: str, args: dict, at: dict) -> dict:
    # What "Create pull request" on an offer did: a change opened on live,
    # starting from the person's words, with Prosper AI working on it (fix.py).
    record = {"state": "working", "doing": "Writing a test of it", "questions": []}
    pull = _call(
        store.chats.open_change,
        agent_id,
        at["chat"],
        at["message"],
        args["title"].strip(),
        args["what"].strip(),
        record,
    )
    label, link = store.label(pull["number"]), _link("pull", pull["number"])
    try:
        agent.start(agent_id, pull["number"])
    except Exception as error:  # noqa: BLE001 - the pull request exists: the card must link it
        # Left failed, like work cut by a restart: a message to it goes on.
        reason = str(error) or type(error).__name__
        store.prosper.set_state(agent_id, pull["number"], "failed")
        text = f"Opened {label} · Prosper AI could not start: {reason} · write to it to retry"
        return {"text": text, "link": link, "said": text}
    said = (
        f"Opened {label}. Prosper AI works on it now: a test of the change, which should fail "
        "on live, then the smallest change, then the whole suite."
    )
    return {"text": f"Opened {label}", "link": link, "said": said}


def _test(copy: dict, name: str, wanted: str) -> dict:
    low = wanted.strip().lower()
    for test in copy["tests"]:
        if low in (test["id"].lower(), test["name"].lower()):
            return test
    names = "; ".join(f'"{t["name"]}"' for t in copy["tests"]) or "none"
    raise ToolError(f'{name} has no test "{wanted}". Its tests: {names}.')


def _open(copy: dict, name: str) -> None:
    if copy["pull"] is not None and copy["state"] != "open":
        raise ToolError(f"{name} is {copy['state']}.")


def run_tests_card(agent_id: str, args: dict) -> dict:
    copy, name = _copy(agent_id, args["pull"])
    _open(copy, name)
    if args["test"]:
        test = _test(copy, name, args["test"])
        return _card("Run a test again", test["name"], f"On {name}", f"{REPEATS} calls")
    count = len(copy["tests"])
    if not count:
        raise ToolError(f"{name} has no tests.")
    return _card(f"Run all {count} tests", "", f"On {name}", f"{count * REPEATS} calls")


def run_tests(agent_id: str, args: dict, at: dict) -> dict:
    copy, name = _copy(agent_id, args["pull"])
    pull = copy["pull"]
    version = copy["number"] if pull is None else None
    if args["test"]:
        test = _test(copy, name, args["test"])
        if pull is not None:
            run = _call(suite.run_pull_test, agent_id, pull, test["id"])
        else:
            run = _call(suite.run_version_test, agent_id, version, test["id"])
        what = f'"{test["name"]}"'
    else:
        if pull is not None:
            run = _call(suite.run_pull_checks, agent_id, pull)
        else:
            run = _call(suite.run_version_checks, agent_id, version)
        what = f"its {len(copy['tests'])} tests"
    alone = f" {run['alone']}" if run.get("alone") else ""
    said = (
        f"Started {what} on {name}, {REPEATS} calls each: results in a minute or two "
        f"(read_tests).{alone}"
    )
    return {"text": f"Running on {name}", "link": _link("tests", pull or 0), "said": said}


def play_calls_card(agent_id: str, args: dict) -> dict:
    version = _live(agent_id)
    return _card(
        "Play a batch of calls",
        "",
        f"On v{version}",
        "simulated callers, each call reviewed into issues",
    )


def play_calls(agent_id: str, args: dict, at: dict) -> dict:
    play = _call(live.play_calls, agent_id)
    said = (
        f"Started a batch on v{play['version']}: the calls come in over a minute or two, "
        "and Prosper AI reviews each one into issues (search_calls, list_issues)."
    )
    return {"text": f"Playing calls on v{play['version']}", "link": _link("calls"), "said": said}


_VERBS = {"snooze": "Snooze", "resolve": "Resolve", "ignore": "Ignore", "reopen": "Reopen"}
_DONE = {"snooze": "Snoozed", "resolve": "Resolved", "ignore": "Ignored", "reopen": "Reopened"}
_FOR = {"day": "For a day", "week": "For a week", "version": "Until the next version is live"}


def _numbers(args: dict) -> list[int]:
    numbers = list(dict.fromkeys(args["issues"]))
    if not numbers:
        raise ToolError("Say which issues.")
    return numbers


def change_issues_card(agent_id: str, args: dict) -> dict:
    change, numbers = args["change"], _numbers(args)
    if change == "snooze" and not args["until"]:
        raise ToolError("Say for how long: a day, a week, or until the next version.")
    issues = [_issue(agent_id, n) for n in numbers]
    refused = [why for issue in issues if (why := store.issues.refusal(issue, change))]
    if refused:
        raise ToolError(" ".join(refused))
    what = " · ".join(issue["title"] for issue in issues)
    return _card(
        f"{_VERBS[change]} {_labels(numbers)}",
        what,
        _FOR[args["until"]] if change == "snooze" else "",
    )


def change_issues(agent_id: str, args: dict, at: dict) -> dict:
    change, numbers = args["change"], _numbers(args)
    route = {
        "snooze": live.snooze,
        "resolve": live.resolve,
        "ignore": live.ignore,
        "reopen": live.reopen,
    }[change]
    extra = (live.Snooze(until=args["until"]),) if change == "snooze" else ()
    done, refused = [], []
    for number in numbers:
        try:
            _call(route, agent_id, number, *extra)
            done.append(number)
        except ToolError as error:
            refused.append(str(error))
    if not done:
        raise ToolError(" ".join(refused))
    text = f"{_DONE[change]} {_labels(done)}" + (f" · {' '.join(refused)}" if refused else "")
    link = _link("issue", done[0]) if len(done) == 1 else _link("issues")
    return {"text": text, "link": link, "said": text}


def change_pull_card(agent_id: str, args: dict) -> dict:
    pull = _call(pulls.get_pull, agent_id, args["number"])
    label = store.label(pull["number"])
    wanted = "open" if args["change"] == "close" else "closed"
    if pull["state"] != wanted:
        raise ToolError(f"{label} is {pull['state']}.")
    if args["change"] == "close":
        return _card(f"Close {label}", pull["title"], "Its changes stay in it; it can be reopened")
    return _card(f"Reopen {label}", pull["title"], "As it was; its checks run again on a change")


def change_pull(agent_id: str, args: dict, at: dict) -> dict:
    route = pulls.close_pull if args["change"] == "close" else pulls.reopen_pull
    pull = _call(route, agent_id, args["number"])
    text = f"{'Closed' if args['change'] == 'close' else 'Reopened'} {store.label(pull['number'])}"
    return {"text": text, "link": _link("pull", pull["number"]), "said": text}


def merge_pull_card(agent_id: str, args: dict) -> dict:
    pull = _call(pulls.get_pull, agent_id, args["number"])
    label = store.label(pull["number"])
    if pull["state"] != "open":
        raise ToolError(f"{label} is {pull['state']}.")
    if reason := store.merge_refusal(agent_id, pull["number"]):
        raise ToolError(reason)
    if found := problem(pull["config"]):
        raise ToolError(json.loads(found.body)["detail"])
    after = (_call(pulls._agent, agent_id)["live_version"] or 0) + 1
    checks = pull["checks"] or {}
    passing = (
        f"{checks['passed']} of {checks['total']} tests pass"
        + (f", {checks['flaky']} flaky" if checks["flaky"] else "")
        if checks
        else ""
    )
    return _card(
        f"Merge {label} as v{after}",
        pull["title"],
        f"Calls will use v{after} from then on",
        passing,
        f"Resolves Issue #{pull['fixes']}" if pull["fixes"] else "",
        warnings=pull["warnings"],
    )


def merge_pull(agent_id: str, args: dict, at: dict) -> dict:
    # Do it on a card that showed the warnings is the confirmation a merge asks
    # for; one that showed none is refused if some came up since, in their words.
    anyway = pulls.PullMerge(anyway=bool(at.get("warnings")))
    pull = _call(pulls.merge_pull, agent_id, args["number"], anyway)
    label, version = store.label(pull["number"]), pull["merged_version"]
    said = f"Merged {label} as v{version}: calls use it now."
    if pull["fixes"]:
        said += f" Issue #{pull['fixes']} is resolved with it."
    text = f"Merged {label} · v{version} is live"
    return {"text": text, "link": _link("pull", pull["number"]), "said": said}


def _open_pull(agent_id: str, number: int) -> dict:
    pull = _call(pulls.get_pull, agent_id, number)
    if pull["state"] != "open":
        raise ToolError(f"{store.label(number)} is {pull['state']}.")
    if reason := store.busy(pull):
        raise ToolError(reason)
    return pull


def add_rule_card(agent_id: str, args: dict) -> dict:
    pull = _open_pull(agent_id, args["pull"])
    rule = _body(suite.RuleAdd, step=args["step"], text=args["text"])
    steps = {node["name"] for node in pull["config"]["nodes"]}
    if rule.step is not None and rule.step not in steps:
        raise ToolError(f"{store.label(pull['number'])} has no step '{rule.step}'.")
    return _card(
        f"Add a rule to {store.label(pull['number'])}",
        rule.text,
        _words(rule.step) or "Every step",
        "its checks run again",
    )


def add_rule(agent_id: str, args: dict, at: dict) -> dict:
    rule = _body(suite.RuleAdd, step=args["step"], text=args["text"])
    pull = _call(suite.add_rule, agent_id, args["pull"], rule)
    text = f"Added the rule to {store.label(pull['number'])}"
    return {"text": text, "link": _link("pull", pull["number"]), "said": text + "; checks run."}


def _test_body(args: dict) -> BaseModel:
    return _body(suite.TestAdd, name=args["name"], caller=args["caller"], checks=args["checks"])


def add_test_card(agent_id: str, args: dict) -> dict:
    pull = _open_pull(agent_id, args["pull"])
    test = _test_body(args)
    return _card(
        f"Add a test to {store.label(pull['number'])}",
        test.name,
        f"{len(test.checks)} check{'s' if len(test.checks) != 1 else ''}",
        "its checks run again",
        stored=[f"Caller: {test.caller}", *(f"Check: {check}" for check in test.checks)],
    )


def add_test(agent_id: str, args: dict, at: dict) -> dict:
    pull = _call(suite.add_test, agent_id, args["pull"], _test_body(args))
    text = f"Added the test to {store.label(pull['number'])}"
    return {"text": text, "link": _link("pull", pull["number"]), "said": text + "; checks run."}


# --- Work on a pull request's copy ---------------------------------------------


def _now_event(kind: str, **more) -> dict:
    return work.event(kind, **more)


def _said(text: str, what: str) -> str:
    """`text` as a person will read it, or ToolError: said, short, steps named as words."""
    text = text.strip()
    try:
        agent.check_answer({"answer": text, "links": []}, {})
    except ValueError as error:
        raise ToolError(f"{what}: {error}") from error
    return text


def _shape(pull: dict) -> dict:
    return artifacts.from_config(pull["config"])


def _node(shape: dict, step: str) -> dict:
    name = artifacts.to_name(step)
    found = next((node for node in shape["nodes"] if node["name"] == name), None)
    if found is None:
        steps = ", ".join(_words(node["name"]) for node in shape["nodes"]) or "none yet"
        raise ToolError(f"There is no step '{step}'. The steps: {steps}.")
    return found


def _edge(node: dict, to: str) -> dict:
    name = artifacts.to_name(to)
    found = next(
        (edge for edge in node["edges"] if artifacts.to_name(edge["target"]) == name), None
    )
    if found is None:
        ways = ", ".join(_words(edge["target"]) for edge in node["edges"]) or "nowhere"
        raise ToolError(
            f"{_words(node['name'])} does not move on to '{to}'. It moves on to: {ways}."
        )
    return found


def _write(at: Work, pull: dict, line: str, step: Optional[str] = None, **copy) -> None:
    """Write the change to the copy: said at once while a new agent is drawn (`step`, or the
    line), else kept to go under Prosper AI's next message."""
    if work.building(at.agent_id, pull):
        event = _now_event("step", text=step or line)
        store.prosper.change(at.agent_id, at.number, None, step=event, **copy)
    else:
        store.prosper.change(at.agent_id, at.number, line, **copy)


def _save(at: Work, shape: dict, line: str, step: Optional[str] = None) -> str:
    """The copy with the agent `shape` drew, checked as a save and as Prosper AI's writing."""
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    before = pull["config"]
    drawn = artifacts.to_config(before["name"], shape, before.get("model", DEFAULT_MODEL))
    config = artifacts.keep_extras(drawn, before) if before["nodes"] else drawn
    try:
        artifacts.check_agent(config)
        artifacts.check_concise(config, before if before["nodes"] else None)
    except ValueError as error:
        raise ToolError(str(error)) from error
    work.small_enough(at.agent_id, pull, config)
    _write(at, pull, line, step, config=config)
    return f"Done: {line}."


def draw_agent(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    if pull["kind"] != "setup":
        raise ToolError("Only a setup draws the agent whole: change it one step at a time.")
    shape = args["agent"]
    count = len(shape["nodes"])
    line = f"Drew {count} step{'s' if count != 1 else ''}"
    return _save(
        at, shape, line if not pull["config"]["nodes"] else f"Drew the agent again: {count} steps"
    )


def add_step(at: Work, args: dict) -> str:
    shape = _shape(work.pull_of(at))
    name = artifacts.to_name(args["name"])
    if any(node["name"] == name for node in shape["nodes"]):
        raise ToolError(f"There is a step '{args['name']}' already: change it instead.")
    node = {"name": name, "task": args["task"], "end": args["ends_call"], "edges": args["moves_on"]}
    shape["nodes"].append(node)
    said = _save(at, shape, f"Added step {_words(name)}")
    return f"{said} Nothing moves on to it yet: set_move_on from the step that leads there."


def set_task(at: Work, args: dict) -> str:
    shape = _shape(work.pull_of(at))
    node = _node(shape, args["step"])
    node["task"] = args["task"]
    return _save(at, shape, f"Changed what {_words(node['name'])} says")


def set_move_on(at: Work, args: dict) -> str:
    shape = _shape(work.pull_of(at))
    node = _node(shape, args["step"])
    if node["end"]:
        raise ToolError(f"{_words(node['name'])} ends the call: it moves on nowhere.")
    _node(shape, args["to"])
    if args["instead_of"]:
        edge = _edge(node, args["instead_of"])
        edge.update(target=args["to"], description=args["when"])
    elif any(
        artifacts.to_name(e["target"]) == artifacts.to_name(args["to"]) for e in node["edges"]
    ):
        _edge(node, args["to"])["description"] = args["when"]
    else:
        node["edges"].append({"description": args["when"], "target": args["to"], "fields": []})
    return _save(at, shape, f"Changed when {_words(node['name'])} moves on")


def remove_move_on(at: Work, args: dict) -> str:
    shape = _shape(work.pull_of(at))
    node = _node(shape, args["step"])
    edge = _edge(node, args["to"])
    node["edges"].remove(edge)
    return _save(at, shape, f"Changed when {_words(node['name'])} moves on")


def add_field(at: Work, args: dict) -> str:
    shape = _shape(work.pull_of(at))
    node = _node(shape, args["step"])
    edge = _edge(node, args["to"])
    field = args["field"]
    if any(
        artifacts.to_name(f["name"]) == artifacts.to_name(field["name"]) for f in edge["fields"]
    ):
        raise ToolError(f"It records '{field['name']}' already.")
    if field["type"] == "choice" and len(field["options"]) < 2:
        raise ToolError("A choice needs its options: two at least.")
    edge["fields"].append(field)
    return _save(at, shape, f"Changed what {_words(node['name'])} records")


def remove_field(at: Work, args: dict) -> str:
    shape = _shape(work.pull_of(at))
    node = _node(shape, args["step"])
    edge = _edge(node, args["to"])
    name = artifacts.to_name(args["name"])
    kept = [f for f in edge["fields"] if artifacts.to_name(f["name"]) != name]
    if len(kept) == len(edge["fields"]):
        raise ToolError(f"It records no '{args['name']}' there.")
    edge["fields"] = kept
    return _save(at, shape, f"Changed what {_words(node['name'])} records")


def add_rules(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    if not pull["config"]["nodes"]:
        raise ToolError("Draw the agent first: a rule goes on its steps.")
    steps = {node["name"] for node in pull["config"]["nodes"]}
    sources, answers = _quotable(at.agent_id, pull)
    have = {artifacts.plain(rule["text"]) for rule in pull["rules"]}
    problems = artifacts.Problems()
    added = []
    for rule in args["rules"]:
        try:
            step = artifacts.check_rule(rule, steps)
            if rule["source"] is not None:
                source = {**artifacts.check_quote(rule, sources, answers), "pull": at.number}
            elif pull["kind"] == "setup":
                raise ValueError(
                    f"Rule '{rule['text']}' needs its source: the line of the guidelines it "
                    f"comes from, or '{artifacts.ANSWER}' with the clinic's answer, as its quote."
                )
            else:
                source = work.source_of(at.agent_id, pull)
        except ValueError as error:
            problems.found.append(str(error))
            continue
        if artifacts.plain(rule["text"]) not in have:
            added.append(
                {"id": store.suite.new_id(), "step": step, "text": rule["text"], "source": source}
            )
    try:
        problems.raise_any()
    except ValueError as error:
        raise ToolError(f"Nothing was added. {error}") from error
    if not added:
        return "It has those rules already."
    events = tuple(_now_event("rule", step=r["step"], text=r["text"]) for r in added)
    count = f"{len(added)} rule{'s' if len(added) != 1 else ''}"
    line = f"Wrote {count}, each linked to its line or your answer"
    if work.building(at.agent_id, pull):
        store.prosper.change(
            at.agent_id,
            at.number,
            None,
            rules=[*pull["rules"], *added],
            step=_now_event("step", text=line),
        )
    else:
        store.prosper.change(
            at.agent_id, at.number, None, rules=[*pull["rules"], *added], events=events
        )
    return f"Added {count}."


def _quotable(agent_id: str, pull: dict) -> tuple[list[dict], list[str]]:
    """What a rule may quote: the guidelines, and the clinic's answers."""
    record = store.prosper.work_of(agent_id, pull["number"])
    sources, answered = store.prosper.guidelines(agent_id)
    if pull["kind"] == "setup":
        sources, answered = record.get("sources", []), []
    answers = [q["answer"] for q in [*answered, *record.get("questions", [])] if q["answer"]]
    return sources, answers


def remove_rule(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    rule = next((r for r in pull["rules"] if r["id"] == args["rule"]), None)
    if rule is None:
        raise ToolError(f"There is no rule '{args['rule']}': use an id in brackets.")
    if not store.suite.added_in(rule, at.number):
        raise ToolError(
            f"That rule is live already, and {store.label(at.number)} only adds: "
            "add a rule that says what changes instead."
        )
    rules = [r for r in pull["rules"] if r["id"] != rule["id"]]
    event = _now_event("rule", step=rule["step"], text=rule["text"], removed=True)
    _write_items(at, pull, f"Took out the rule {rule['text']}", event, rules=rules)
    return "Took it out."


def _write_items(at: Work, pull: dict, line: str, event: dict, **copy) -> None:
    if work.building(at.agent_id, pull):
        store.prosper.change(
            at.agent_id, at.number, None, step=_now_event("step", text=line), **copy
        )
    else:
        store.prosper.change(at.agent_id, at.number, None, events=(event,), **copy)


def _checked_tests(pull: dict, tests: list[dict]) -> None:
    try:
        artifacts.check_tests(tests, pull["config"])
    except ValueError as error:
        raise ToolError(str(error)) from error


def add_tests(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    if not pull["config"]["nodes"]:
        raise ToolError("Draw the agent first: a test calls it.")
    _checked_tests(pull, args["tests"])
    if (
        pull["kind"] == "setup"
        and len(pull["tests"]) + len(args["tests"]) > artifacts.SETUP_TESTS[1]
    ):
        raise ToolError(
            f"A setup writes {artifacts.SETUP_TESTS[1]} tests at most: the ones that matter."
        )
    source = work.source_of(at.agent_id, pull)
    added = [{"id": store.suite.new_id(), **test, "source": source} for test in args["tests"]]
    count = f"{len(added)} test{'s' if len(added) != 1 else ''}"
    events = tuple(_now_event("test", text=t["name"]) for t in added)
    tests = [*pull["tests"], *added]
    if work.building(at.agent_id, pull):
        store.prosper.change(
            at.agent_id,
            at.number,
            None,
            tests=tests,
            step=_now_event("step", text=f"Wrote {count}"),
        )
    else:
        store.prosper.change(at.agent_id, at.number, None, tests=tests, events=events)
    return f"Added {count}: " + ", ".join(f"[{t['id']}] {t['name']}" for t in added)


def _the_test(pull: dict, wanted: str) -> dict:
    low = wanted.strip().lower()
    for test in pull["tests"]:
        if low in (test["id"].lower(), test["name"].lower()):
            return test
    names = "; ".join(f"[{t['id']}] {t['name']}" for t in pull["tests"]) or "none"
    raise ToolError(f'There is no test "{wanted}". Its tests: {names}.')


def rewrite_test(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    test = _the_test(pull, args["test"])
    work.may_change_test(pull, test, removing=False)
    fields = {key: args[key] for key in ("name", "caller", "checks")}
    _checked_tests(pull, [fields])
    why = _said(args["why"], "Why")
    tests = [{**t, **fields} if t["id"] == test["id"] else t for t in pull["tests"]]
    event = _now_event("test", text=fields["name"], rewritten=True, why=why)
    _write_items(at, pull, f"Rewrote the test {fields['name']}", event, tests=tests)
    return "Rewrote it."


def remove_test(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    test = _the_test(pull, args["test"])
    work.may_change_test(pull, test, removing=True)
    tests = [t for t in pull["tests"] if t["id"] != test["id"]]
    event = _now_event("test", text=test["name"], removed=True)
    _write_items(at, pull, f"Took out the test {test['name']}", event, tests=tests)
    return "Took it out."


def ask(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    record = store.prosper.work_of(at.agent_id, at.number)
    first = pull["kind"] == "setup" and "asked" not in record.get("built", [])
    steps = {node["name"] for node in pull["config"]["nodes"]} or None
    try:
        artifacts.check_questions(args["questions"], None if first else steps)
    except ValueError as error:
        raise ToolError(str(error)) from error
    if first and not args["questions"]:
        store.prosper.mark_built(at.agent_id, at.number, "asked")
        line = f"Found no gaps in the guidelines that change how {pull['config']['name']} behaves"
        store.prosper.log(at.agent_id, at.number, _now_event("step", text=line))
        return "Nothing to ask: go on and draw the agent."
    if not args["questions"]:
        raise ToolError("Ask at least one question, or say what you need in your answer instead.")
    said = _said(args["said"], "What you say before the questions")
    questions = [
        {
            "text": question["text"],
            "options": [
                {
                    "label": option["label"],
                    "rule": option["rule"]
                    and {
                        "step": artifacts.step_of(option["rule"]["step"]),
                        "text": option["rule"]["text"],
                    },
                }
                for option in question["options"]
            ],
        }
        for question in args["questions"]
    ]
    store.prosper.say(at.agent_id, at.number, _now_event("message", text=said))
    store.prosper.ask(at.agent_id, at.number, questions, setup=first)
    if first:
        store.prosper.mark_built(at.agent_id, at.number, "asked")
    at.waiting = True
    return "Asked. Stop here: their answers start your next turn."


def reproduce(at: Work, args: dict) -> str:
    return work.reproduce(at, {key: args[key] for key in ("name", "caller", "checks")})


def run_all(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.ready_to_run(at, pull)
    if store.prosper.unsaid(at.agent_id, at.number):
        if not args["said"].strip():
            raise ToolError("Say in `said` what you changed since the tests last ran, and why.")
        said = _said(args["said"], "What you changed")
        kind = "message" if pull["kind"] == "setup" else "proposed"
        store.prosper.say(at.agent_id, at.number, _now_event(kind, text=said))
    at.runs += 1
    run = work.run(at)
    pull = work.pull_of(at)
    checks = store.runs.summary(run)
    if pull["kind"] in ("fix", "change") and checks and checks["state"] == "passed":
        work.proved(at.agent_id, at.number)
    told = work.results(at.agent_id, pull)
    own = next((t for t in pull["tests"] if work.is_test_of(t, at.number)), None)
    result = next((r for r in run["tests"] if own and r["id"] == own["id"]), None)
    if result is not None and store.runs.verdict(result, run["repeats"]) == "flaky":
        told += (
            "\n\nThe test of what this pull request is for passes only 2/3: the problem may "
            "still happen in some calls."
        )
    return told


def run_one(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    work.may_edit(at, pull)
    test = _the_test(pull, args["test"])
    run = work.run(at, test["id"])
    checks = store.runs.summary(run)
    if pull["kind"] in ("fix", "change") and checks and checks["state"] == "passed":
        work.proved(at.agent_id, at.number)  # the run it went into passes now
    result = next(r for r in run["tests"] if r["id"] == test["id"])
    score = f"{sum(1 for r in result['runs'] if r['passed'])}/{len(result['runs'])}"
    kind = store.runs.verdict(result, run["repeats"])
    bad = [r for r in result["runs"] if not r["passed"]]
    how = f"\n{the_call(bad[0])}" if bad else ""
    return f"{test['name']}, run again: {kind}, {score}.{how}"


def read_results(at: Work, args: dict) -> str:
    return work.results(at.agent_id, work.pull_of(at))


def read_test_call(at: Work, args: dict) -> str:
    pull = work.pull_of(at)
    test = _the_test(pull, args["test"])
    return work.test_call(at.agent_id, pull, test["id"], args["call"])


_TEST = artifacts._object(
    name=_TEXT,
    caller={**_TEXT, "description": "Who calls and what they want, to the person playing them."},
    checks=artifacts._list(_TEXT),
)
_RULE = artifacts._object(step=_maybe(_TEXT), text=_TEXT, source=_maybe(_TEXT), quote=_maybe(_TEXT))
_OPTION = artifacts._object(
    label=_TEXT,
    rule={"anyOf": [artifacts._object(step=_maybe(_TEXT), text=_TEXT), {"type": "null"}]},
)
_QUESTION = artifacts._object(text=_TEXT, options=artifacts._list(_OPTION))
_PULL = "An open pull request's number; null for live."
_STATES = _enum("open", "snoozed", "resolved", "ignored")

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            "search_calls",
            "Search the agent's calls; every filter is optional (null). Lists them a line each.",
            _args(
                caller=_maybe(_TEXT),
                outcome=_maybe(
                    _enum("booked", "rescheduled", "cancelled", "callback", "answered", "hung_up")
                ),
                issue=_maybe(_INT),
                version=_maybe(_INT),
                day=_maybe({"type": "string", "description": "YYYY-MM-DD"}),
            ),
            read=search_calls,
        ),
        Tool(
            "read_call",
            "Read one call whole: who called, path, what it recorded, transcript, findings.",
            _args(call=_INT),
            read=read_call,
        ),
        Tool(
            "list_issues",
            "List the issues, in one state or all.",
            _args(state=_maybe(_STATES)),
            read=list_issues,
        ),
        Tool(
            "read_issue",
            "Read one issue: its calls with the bad turns, the pull requests fixing it, its log.",
            _args(number=_INT),
            read=read_issue,
        ),
        Tool(
            "list_pulls",
            "List the pull requests, in one state or all.",
            _args(state=_maybe(_enum("open", "merged", "closed"))),
            read=list_pulls,
        ),
        Tool(
            "read_pull",
            "Read one pull request: its state, checks, the rules and tests it adds, its log.",
            _args(number=_INT),
            read=read_pull,
        ),
        Tool(
            "read_tests",
            "Read the tests of live or of an open pull request, and how each last went.",
            _args(pull=_maybe({**_INT, "description": _PULL})),
            read=read_tests,
        ),
        Tool(
            "read_agent",
            "Read the steps and rules of live, of a pull request, or of an older version.",
            _args(
                pull=_maybe({**_INT, "description": "A pull request's number; null for live."}),
                version=_maybe({**_INT, "description": "An older version's number, or null."}),
            ),
            read=read_agent,
        ),
        Tool("list_versions", "List the versions, live first.", _args(), read=list_versions),
        Tool(
            "open_issue",
            "Open an issue for something that went wrong (a clinic's complaint, a call).",
            _args(
                title=_TEXT,
                description=_TEXT,
                step=_maybe({**_TEXT, "description": "A live step's stored name, or null."}),
                severity=_maybe(_enum("safety", "booking", "experience")),
                reported=_enum("you", "clinic"),
                calls=artifacts._list(_INT),
            ),
            card=open_issue_card,
            act=open_issue,
        ),
        Tool(
            "tidy_issue",
            "Rewrite an issue a person reported: plain title, step, severity, calls showing it.",
            _args(number=_INT),
            card=tidy_issue_card,
            act=tidy_issue,
        ),
        Tool(
            "fix_issue",
            "Fix an issue with Prosper AI: a pull request with a test that reproduces it, "
            "the smallest change and the suite.",
            _args(number=_INT),
            card=fix_issue_card,
            act=fix_issue,
        ),
        Tool(
            "open_pull_request",
            "Open a pull request for a change the person asked for, on live: Prosper AI writes "
            "a test of it, makes the smallest change and runs the suite.",
            _args(
                title={**_TEXT, "description": "A short imperative: 'Ask who the visit is for'."},
                what={**_TEXT, "description": "One sentence on what it changes in the agent."},
            ),
            card=open_pull_card,
            act=open_pull,
        ),
        Tool(
            "run_tests",
            "Run one test again (by its name), or all the tests, on live or an open pull request.",
            _args(
                pull=_maybe({**_INT, "description": _PULL}),
                test=_maybe({**_TEXT, "description": "The test's name; null for all of them."}),
            ),
            card=run_tests_card,
            act=run_tests,
        ),
        Tool(
            "play_calls",
            "Play a batch of simulated calls on live; each is reviewed into issues.",
            _args(),
            card=play_calls_card,
            act=play_calls,
        ),
        Tool(
            "change_issues",
            "Snooze, resolve, ignore or reopen one or more issues.",
            _args(
                change=_enum("snooze", "resolve", "ignore", "reopen"),
                issues=artifacts._list(_INT),
                until=_maybe(_enum("day", "week", "version")),
            ),
            card=change_issues_card,
            act=change_issues,
        ),
        Tool(
            "change_pull",
            "Close an open pull request, or reopen a closed one.",
            _args(change=_enum("close", "reopen"), number=_INT),
            card=change_pull_card,
            act=change_pull,
        ),
        Tool(
            "merge_pull",
            "Merge a pull request: it becomes the next version, and calls use it.",
            _args(number=_INT),
            card=merge_pull_card,
            act=merge_pull,
        ),
        Tool(
            "add_rule",
            "Add a rule to an open pull request.",
            _args(
                pull=_INT,
                step=_maybe({**_TEXT, "description": "A step's stored name; null for every step."}),
                text=_TEXT,
            ),
            card=add_rule_card,
            act=add_rule,
        ),
        Tool(
            "add_test",
            "Add a test to an open pull request.",
            _args(
                pull=_INT,
                name=_TEXT,
                caller={**_TEXT, "description": "Who calls and what they want."},
                checks=artifacts._list(_TEXT),
            ),
            card=add_test_card,
            act=add_test,
        ),
        # --- In a pull request's conversation: work on its copy, no card.
        Tool(
            "ask",
            "Ask the person questions with 2 or 3 options each, and stop until they answer. "
            "In a setup, first of all: what the guidelines leave open (no questions: an empty "
            "list, and go on). An option's rule is what picking it adds; null for none.",
            _args(
                said={**_TEXT, "description": "One sentence to the person before the questions."},
                questions=artifacts._list(_QUESTION),
            ),
            edit=ask,
            doing="Asking you",
        ),
        Tool(
            "draw_agent",
            "A setup only: draw the whole agent (persona, start step, steps with how each moves "
            "on and what it records). Steps are snake_case names.",
            _args(agent=artifacts.AGENT),
            edit=draw_agent,
            doing="Drawing the steps",
        ),
        Tool(
            "add_step",
            "Add a step, with how it moves on (none if it ends the call). Then make another "
            "step move on to it with set_move_on.",
            _args(
                name=_TEXT,
                task=_TEXT,
                ends_call={"type": "boolean"},
                moves_on=artifacts._list(artifacts._EDGE),
            ),
            edit=add_step,
            doing="Adding a step",
        ),
        Tool(
            "set_task",
            "Rewrite what a step tells the agent to do: at most 3 short sentences.",
            _args(step=_TEXT, task=_TEXT),
            edit=set_task,
            doing="Changing a step",
        ),
        Tool(
            "set_move_on",
            "Set when `step` moves on to `to`: its condition. Adds the way on if it has none to "
            "`to`; with `instead_of`, the way that went there now goes to `to`.",
            _args(
                step=_TEXT,
                to=_TEXT,
                when={**_TEXT, "description": "The condition, plainly: 'Once the caller ...'"},
                instead_of=_maybe({**_TEXT, "description": "The step it moved on to before."}),
            ),
            edit=set_move_on,
            doing="Changing when a step moves on",
        ),
        Tool(
            "remove_move_on",
            "Take out the way `step` moves on to `to`.",
            _args(step=_TEXT, to=_TEXT),
            edit=remove_move_on,
            doing="Changing when a step moves on",
        ),
        Tool(
            "add_field",
            "Make the way `step` moves on to `to` record a field.",
            _args(step=_TEXT, to=_TEXT, field=artifacts._FIELD),
            edit=add_field,
            doing="Changing what a step records",
        ),
        Tool(
            "remove_field",
            "Stop the way `step` moves on to `to` recording a field.",
            _args(step=_TEXT, to=_TEXT, name=_TEXT),
            edit=remove_field,
            doing="Changing what a step records",
        ),
        Tool(
            "add_rules",
            "Add rules: one short sentence each, on a step or (null) every step. `source` and "
            "`quote`: the source's name and its line word for word, or 'your answer' and the "
            "clinic's answer; null on a fix or a change, whose rules come from what it is for.",
            _args(rules=artifacts._list(_RULE)),
            edit=add_rules,
            doing="Writing the rules",
        ),
        Tool(
            "remove_rule",
            "Take out a rule this pull request added, by its id.",
            _args(rule=_TEXT),
            edit=remove_rule,
            doing="Changing the rules",
        ),
        Tool(
            "add_tests",
            "Add tests: each a simulated caller and 2 to 4 checks.",
            _args(tests=artifacts._list(_TEST)),
            edit=add_tests,
            doing="Writing the tests",
        ),
        Tool(
            "rewrite_test",
            "Rewrite a test (by its id) that asks for more than the guidelines say, saying why.",
            _args(test=_TEXT, name=_TEXT, caller=_TEXT, checks=artifacts._list(_TEXT), why=_TEXT),
            edit=rewrite_test,
            doing="Rewriting a test",
        ),
        Tool(
            "remove_test",
            "Take out a test this pull request added, by its id. Never in a setup.",
            _args(test=_TEXT),
            edit=remove_test,
            doing="Changing the tests",
        ),
        Tool(
            "reproduce",
            "A fix or a change, first: play a test on the version it is based on, 3 calls. "
            "Failing, it joins the copy as the test of what the pull request is for.",
            _args(name=_TEXT, caller=_TEXT, checks=artifacts._list(_TEXT)),
            edit=reproduce,
            doing="Reproducing it",
        ),
        Tool(
            "run_all",
            "Run all the copy's tests, 3 calls each, and wait for how they went (minutes).",
            _args(
                said={
                    **_TEXT,
                    "description": "What you changed since they last ran, and why, for the "
                    "person: one or two sentences, starting with a verb. Empty if nothing.",
                }
            ),
            edit=run_all,
            doing="Running the tests",
        ),
        Tool(
            "run_one",
            "Run one test of the copy again, 3 calls, by its id or name.",
            _args(test=_TEXT),
            edit=run_one,
            doing="Running a test again",
        ),
        Tool(
            "read_results",
            "Read how the copy's tests last went, with a call of each that failed.",
            _args(),
            edit=read_results,
            doing="Reading the checks",
        ),
        Tool(
            "read_test_call",
            "Read one call of a test in the copy's last run, whole: `call` from 1.",
            _args(test=_TEXT, call=_INT),
            edit=read_test_call,
            doing="Reading a test's call",
        ),
    ]
}
