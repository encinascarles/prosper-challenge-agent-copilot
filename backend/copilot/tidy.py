#
# Tidy with Prosper AI: a person reported an issue in their own words (often
# the clinic's email, pasted). Asked to, Prosper AI rewrites the title in
# plain words, picks the step and the severity, and points at up to three
# stored calls that show it.
#
# One request, like an answer in Ask: the issue, the live version's steps and
# the latest calls, one line each (who, when, the steps it went through and
# what it recorded: enough to spot "booked on a Sunday"). Nothing is written:
# the person sees the before and after, and keeps it (a PATCH of the issue)
# or not. The answer is checked in code: a step that exists, calls that exist.
#

import json

import store

from . import setup
from .artifacts import _list, _object
from .ask import _STORED_NAME, _when
from .calls import _ENDED

MAX_TITLE_CHARS = 80
MAX_CALLS = 3
CALLS_LISTED = 40  # the latest, one line each
SEVERITIES = ("safety", "booking", "experience")

_TEXT = {"type": "string"}
TIDY = _object(
    title=_TEXT,
    step=_TEXT,
    severity={"type": "string", "enum": list(SEVERITIES)},
    calls=_list({"type": "integer"}),
)


def tidy(agent_id: str, number: int) -> dict:
    """Prosper AI's tidy of reported issue `number`: { title, step, severity, calls, usd }.

    Raises NotFound, Conflict for an issue Prosper AI found itself (its words
    are already its own), or llm.Failed.
    """
    issue = store.issues.get_issue(agent_id, number)
    if issue is None:
        raise store.NotFound(f"The agent has no {store.issues.label(number)}.")
    if issue["reported"] is None:
        found = store.issues.label(number)
        raise store.Conflict(f"{found} was found in calls: it is tidy already.")
    live = store.get_version(agent_id, store.get_agent(agent_id)["live_version"])
    if live is None:
        raise store.Conflict("The agent is not live yet.")
    steps = {node["name"] for node in live["config"]["nodes"]}
    calls = store.calls.list_calls(agent_id)[:CALLS_LISTED]
    known = {call["id"] for call in calls}
    llm = setup.new_llm()
    answer = llm.ask(
        "tidy",
        _facts(agent_id, issue, live, calls),
        TIDY,
        lambda a: check_tidy(a, steps, known),
    )
    linked = {found["call"] for found in issue["findings"]}
    return {
        **answer,
        "calls": [c for c in dict.fromkeys(answer["calls"]) if c not in linked],
        "usd": llm.usage["usd"],
    }


def check_tidy(answer: dict, steps: set[str], calls: set[int]) -> None:
    """Raise ValueError with what is wrong: a long title, a step or a call that does not exist."""
    title = answer["title"].strip()
    if not title or len(title) > MAX_TITLE_CHARS:
        raise ValueError(f"The title is one line of at most {MAX_TITLE_CHARS} characters.")
    if found := _STORED_NAME.search(title):
        raise ValueError(f'Name steps as words in the title, never "{found.group()}".')
    if answer["step"] and answer["step"] not in steps:
        raise ValueError(
            f'There is no step "{answer["step"]}": use a step\'s exact name, or "" if unsure.'
        )
    if len(answer["calls"]) > MAX_CALLS:
        raise ValueError(f"Point at {MAX_CALLS} calls at most: the ones that show it best.")
    for call in answer["calls"]:
        if call not in calls:
            raise ValueError(f"There is no call {call} in the list: use only listed calls.")


def _facts(agent_id: str, issue: dict, live: dict, calls: list[dict]) -> str:
    who = "the clinic" if issue["reported"] == "clinic" else "the deployment team"
    steps = "\n".join(f"- {node['name']}: {_task(node)}" for node in live["config"]["nodes"])
    lines = [_line(agent_id, call) for call in calls]
    return (
        f"The issue, reported by {who}:\nTitle: {issue['title']}\n"
        f"What happened: {issue['description']}\n"
        f"Step they named: {issue['step'] or 'not sure'} · "
        f"severity they gave: {issue['severity'] or 'none'}\n\n"
        f"The agent's steps, v{live['number']} (live):\n{steps}\n\n"
        f"Its latest calls, one line each:\n" + ("\n".join(lines) or "(none)")
    )


def _task(node: dict) -> str:
    text = " ".join(m.get("content", "") for m in node.get("task_messages", []))
    return text[:160]


def _line(agent_id: str, summary: dict) -> str:
    call = store.calls.get_call(agent_id, summary["id"]) or {"path": [], "situation": ""}
    path = " > ".join(step["node"] for step in call["path"]) or "nowhere"
    collected = {k: v for step in call["path"] for k, v in (step["collected"] or {}).items()}
    return (
        f"- call {summary['id']} · {summary['caller']} · {_when(summary['at'])} · "
        f"v{summary['version']} · {summary['outcome'] or 'not reviewed'} · "
        f"{_ENDED.get(summary['ended'], summary['ended'])} · steps: {path} · "
        f"recorded: {json.dumps(collected) if collected else 'nothing'}"
    )
