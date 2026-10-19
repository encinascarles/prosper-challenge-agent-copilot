#
# Calls and issues API — what callers got from the live version, and what
# Prosper AI found wrong in it.
#
# "Play calls" starts a batch of simulated calls on the live version and
# returns at once; the calls are stored as they end and reviewed a moment
# later (copilot/calls.py), and the Calls page reads them from here while the
# batch runs. Issues are read here too, and put aside or closed by hand:
# snoozed, resolved, ignored or reopened. Fixing one is a pull request.
#

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import simulate
import store
from copilot import calls as playing

from . import checks
from .models import YOU
from .pulls import _MISSING, _REFUSED, _agent, _answer

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["calls and issues"])

Outcome = Literal["booked", "rescheduled", "cancelled", "callback", "answered", "hung_up"]
Severity = Literal["safety", "booking", "experience"]
IssueState = Literal["open", "snoozed", "resolved", "ignored"]


class Play(BaseModel):
    """A batch of simulated calls on the live version."""

    id: int
    version: int
    state: Literal["working", "done", "failed", "stopped"]
    callers: int  # how many calls it makes; 0 until Prosper AI has picked the callers
    usage: dict[str, float]  # USD spent so far, by part: callers, calls, reviews
    error: str | None
    started_at: str
    finished_at: str | None


class CallSummary(BaseModel):
    id: int
    version: int  # the version that answered
    caller: str
    at: str
    seconds: int  # estimated from the transcript: simulated calls have no audio
    ended: str  # agent_ended, caller_hung_up, turn_cap, stuck or end_not_reached
    review: Literal["pending", "done", "failed"]  # Prosper AI's review of it
    outcome: Outcome | None  # once reviewed
    issues: list[int]  # the issues its findings were grouped into


class CallsPage(BaseModel):
    play: Play | None  # the latest batch, going or not
    calls: list[CallSummary]  # latest first


class CallCheck(BaseModel):
    text: str
    passed: bool
    rule: str  # the id of the agent's rule it comes from, or "" for the guidelines


class CallFinding(BaseModel):
    issue: int
    title: str
    state: IssueState
    check: str  # the text of the check it failed
    step: str
    turn: int  # index of the line in the transcript
    quote: str
    why: str


class Line(BaseModel):
    role: Literal["agent", "caller"]
    text: str
    node: str | None


class PathStep(BaseModel):
    node: str
    edge: str | None
    collected: dict[str, Any]


class Call(CallSummary):
    situation: str  # the simulated caller's brief
    path: list[PathStep]
    transcript: list[Line]
    checks: list[CallCheck]
    findings: list[CallFinding]
    usage: dict[str, float]  # USD: agent, caller, review


class IssueSummary(BaseModel):
    number: int
    title: str
    step: str
    severity: Severity
    description: str
    state: IssueState
    snooze: dict[str, Any] | None  # { until: ISO time } or { version: n }
    calls: int
    first_seen: str | None
    last_seen: str | None
    created_at: str
    updated_at: str


class IssueLine(Line):
    index: int  # in the call's transcript


class IssueCall(BaseModel):
    call: int
    caller: str
    at: str
    seconds: int
    outcome: Outcome | None
    version: int
    check: str
    turn: int  # the bad turn
    quote: str
    why: str
    lines: list[IssueLine]  # the bad turn, with the line before it


class IssueEvent(BaseModel):
    # opened and seen: by Prosper AI, from a call; woke: a snooze ended
    type: Literal["opened", "seen", "snoozed", "woke", "resolved", "ignored", "reopened"]
    by: str
    at: str
    call: int | None = None
    caller: str | None = None
    text: str | None = None


class Issue(IssueSummary):
    findings: list[IssueCall]  # its calls, latest first
    events: list[IssueEvent]


class Snooze(BaseModel):
    until: Literal["day", "week", "version"] = Field(
        description="For a day, for a week, or until the next version is live."
    )


@router.post("/calls/play", status_code=202, response_model=Play, responses=_MISSING | _REFUSED)
def play_calls(agent_id: str) -> dict:
    """Start a batch of simulated calls on the live version; they come in over a minute or two."""
    return _answer(playing.play, agent_id, checks.services or simulate.Services())


@router.get("/calls", response_model=CallsPage, responses=_MISSING)
def list_calls(agent_id: str) -> dict:
    calls = _answer(store.calls.list_calls, agent_id)
    return {"play": store.calls.latest_play(agent_id), "calls": calls}


@router.get("/calls/{call_id}", response_model=Call, responses=_MISSING)
def get_call(agent_id: str, call_id: int) -> dict:
    _agent(agent_id)
    call = store.calls.get_call(agent_id, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"The agent has no call {call_id}.")
    return call


@router.get("/issues", response_model=list[IssueSummary], responses=_MISSING)
def list_issues(agent_id: str) -> list[dict]:
    return _answer(store.issues.list_issues, agent_id)


@router.get("/issues/{number}", response_model=Issue, responses=_MISSING)
def get_issue(agent_id: str, number: int) -> dict:
    _agent(agent_id)
    issue = store.issues.get_issue(agent_id, number)
    if issue is None:
        missing = f"The agent has no {store.issues.label(number)}."
        raise HTTPException(status_code=404, detail=missing)
    return issue


@router.post("/issues/{number}/snooze", response_model=Issue, responses=_MISSING | _REFUSED)
def snooze(agent_id: str, number: int, body: Snooze) -> dict:
    return _answer(store.issues.snooze, agent_id, number, body.until, YOU)


@router.post("/issues/{number}/resolve", response_model=Issue, responses=_MISSING | _REFUSED)
def resolve(agent_id: str, number: int) -> dict:
    return _answer(store.issues.resolve, agent_id, number, YOU)


@router.post("/issues/{number}/ignore", response_model=Issue, responses=_MISSING | _REFUSED)
def ignore(agent_id: str, number: int) -> dict:
    return _answer(store.issues.ignore, agent_id, number, YOU)


@router.post("/issues/{number}/reopen", response_model=Issue, responses=_MISSING | _REFUSED)
def reopen(agent_id: str, number: int) -> dict:
    return _answer(store.issues.reopen, agent_id, number, YOU)
