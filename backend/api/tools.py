#
# Prosper AI's tools in Ask Prosper AI: what it reads, and what it does once
# the person says so. copilot/ask.py runs them; this is what they are.
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

import json
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

import store
from copilot import artifacts, setup
from copilot.ask import (
    Tool,
    ToolError,
    call_in_full,
    call_line,
    copy_of,
    issue_line,
    pull_line,
    tests_of,
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


def _card(title: str, what: str = "", *meta: str) -> dict:
    return {"title": title, "what": what, "meta": [m for m in meta if m]}


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
    work = {"state": "working", "doing": "Writing a test of it", "questions": []}
    pull = _call(
        store.chats.open_change,
        agent_id,
        at["chat"],
        at["message"],
        args["title"].strip(),
        args["what"].strip(),
        work,
    )
    label, link = store.label(pull["number"]), _link("pull", pull["number"])
    try:
        setup.fix(agent_id, pull["number"])
    except Exception as error:  # noqa: BLE001 - the pull request exists: the card must link it
        # Left as a failed job, like one cut by a restart: a message to it retries.
        reason = str(error) or type(error).__name__
        store.prosper.set_job(agent_id, pull["number"], {"kind": "fix"})
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
    )


def merge_pull(agent_id: str, args: dict, at: dict) -> dict:
    pull = _call(pulls.merge_pull, agent_id, args["number"])
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
    )


def add_test(agent_id: str, args: dict, at: dict) -> dict:
    pull = _call(suite.add_test, agent_id, args["pull"], _test_body(args))
    text = f"Added the test to {store.label(pull['number'])}"
    return {"text": text, "link": _link("pull", pull["number"]), "said": text + "; checks run."}


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
    ]
}
