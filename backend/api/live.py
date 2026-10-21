#
# Calls and issues API — what callers got from the live version, and what
# Prosper AI found wrong in it.
#
# "Play calls" starts a batch of simulated calls on the live version and
# returns at once; the calls are stored as they end and reviewed a moment
# later (copilot/calls.py), and the Calls page reads them from here while the
# batch runs. Issues are read here too, and put aside or closed by hand:
# snoozed, resolved, ignored or reopened. Fixing one is a pull request opened
# from it, by the person or by Prosper AI. A person reports one here too (a
# complaint from the clinic), and Prosper AI can tidy what they wrote.
#
# Test calls (the voice calls a person places from Build) are listed apart,
# and reviewed by Prosper AI only when asked; what it finds stays on the call.
#

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

import simulate
import store
from copilot import agent, tidy
from copilot import calls as playing
from copilot.llm import Failed

from . import checks
from .models import YOU
from .pulls import _MISSING, _REFUSED, Pull, _agent, _answer

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
    play: int | None  # the batch it came in
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


class TestCallSummary(BaseModel):
    id: int
    pull: int | None  # the pull request whose copy it called; null for live
    version: int | None  # the live version it called
    by: str
    at: str
    seconds: int  # timed: it was a voice call
    ended: Literal["agent_ended", "caller_hung_up"]
    review: Literal["none", "pending", "done", "failed"]  # Prosper AI's, only when asked
    outcome: Outcome | None
    flagged: int  # how many checks it failed, once reviewed


class TestCallFinding(BaseModel):
    check: str
    step: str
    turn: int
    quote: str
    why: str
    title: str
    severity: Severity
    description: str


class TestCallPage(TestCallSummary):
    path: list[PathStep]
    transcript: list[Line]
    checks: list[CallCheck]
    findings: list[TestCallFinding]  # never filed as issues
    usage: dict[str, float]


class Fixed(BaseModel):
    pull: int
    version: int  # the version it was fixed in


class FixPull(BaseModel):
    number: int
    title: str
    state: Literal["open", "merged", "closed"]
    merged_version: int | None


class IssueSummary(BaseModel):
    number: int
    title: str
    step: str  # "" when the person who reported it was not sure
    severity: Severity | None  # None when the person who reported it did not say
    description: str
    reported: Literal["you", "clinic"] | None  # who flagged it; None: Prosper AI, from calls
    state: IssueState
    snooze: dict[str, Any] | None  # { until: ISO time } or { version: n }
    fixed: Fixed | None  # the fix that resolved it, while it stays resolved
    pulls: list[FixPull]  # the pull requests that fix it, newest first
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
    turn: int  # the bad turn; -1 for a call a person linked, as a whole
    quote: str
    why: str
    lines: list[IssueLine]  # the bad turn, with the line before it; none for a linked call


class IssueEvent(BaseModel):
    # opened and seen: by Prosper AI, from a call; woke: a snooze ended.
    # A pull request fixing it: fixing (opened for it), unlinked (closed),
    # relinked (reopened), fixed (merged: resolved in `version`), and
    # came_back: a call on the fixed version had the problem again.
    # reported: a person opened it (`text`: "you" or "clinic"), then edited
    # it, or kept what Prosper AI tidied; titled: Prosper AI wrote the title
    # it was reported without.
    type: Literal[
        "opened",
        "reported",
        "edited",
        "tidied",
        "titled",
        "seen",
        "snoozed",
        "woke",
        "resolved",
        "ignored",
        "reopened",
        "fixing",
        "unlinked",
        "relinked",
        "fixed",
        "fix_merged",  # merged while the issue was ignored or resolved: `text` says which
        "came_back",
    ]
    by: str
    at: str
    call: int | None = None
    caller: str | None = None
    text: str | None = None
    pull: int | None = None
    version: int | None = None


class Issue(IssueSummary):
    findings: list[IssueCall]  # its calls, latest first
    events: list[IssueEvent]


class Fix(BaseModel):
    prosper: bool = Field(
        description="Prosper AI reproduces it with a test and proposes the change; "
        "without it, the pull request is yours to edit in Build."
    )


class IssueReport(BaseModel):
    """An issue a person reports: what they or the clinic saw go wrong."""

    title: str = Field(
        default="", max_length=120, description="Empty: Prosper AI writes it from what happened."
    )
    description: str = Field(min_length=1, max_length=4000, description="What happened.")
    step: str = Field(default="", description="The step it happens in; empty when not sure.")
    severity: Severity | None = None
    reported: Literal["you", "clinic"] = Field(
        default="you", description="Who flagged it: you, or the clinic."
    )
    calls: list[int] = Field(default=[], max_length=10, description="Calls that show it.")

    @field_validator("description")
    @classmethod
    def _said(cls, text: str) -> str:
        # The title may be left to Prosper AI; what happened is the report itself.
        if not text.strip():
            raise ValueError("Say what happened: it is what the issue is about.")
        return text


class IssueEdit(BaseModel):
    """A change to a reported issue: only the fields sent change; `calls` are linked too."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    step: str | None = None
    severity: Severity | None = None
    calls: list[int] = Field(default=[], max_length=10)
    tidied: bool = Field(default=False, description="These are Prosper AI's words, kept.")

    @field_validator("title", "description")
    @classmethod
    def _words(cls, text: str | None) -> str:
        # Left out keeps them; null would blank an issue that must say something.
        if text is None:
            raise ValueError("An issue keeps a title and what happened: leave it out to keep it.")
        return text


class Tidied(BaseModel):
    """What Prosper AI would make of a reported issue; nothing is kept until the person says."""

    title: str
    step: str  # "" when nothing says which
    severity: Severity
    calls: list[int]  # calls that show it, not linked yet: up to 3
    usd: float  # what the request cost


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


@router.get("/test-calls", response_model=list[TestCallSummary], responses=_MISSING)
def list_test_calls(agent_id: str) -> list[dict]:
    """The voice calls placed from Build, latest first."""
    return _answer(store.test_calls.list_test_calls, agent_id)


@router.get("/test-calls/{call_id}", response_model=TestCallPage, responses=_MISSING)
def get_test_call(agent_id: str, call_id: int) -> dict:
    _agent(agent_id)
    call = store.test_calls.get_test_call(agent_id, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail=f"The agent has no test call {call_id}.")
    return call


@router.post(
    "/test-calls/{call_id}/review",
    status_code=202,
    response_model=TestCallPage,
    responses=_MISSING | _REFUSED,
)
def review_test_call(agent_id: str, call_id: int) -> dict:
    """Have Prosper AI review the test call as it reviews calls; nothing is filed as an issue."""
    _agent(agent_id)
    return _answer(playing.review_test_call, agent_id, call_id)


@router.get("/issues", response_model=list[IssueSummary], responses=_MISSING)
def list_issues(agent_id: str) -> list[dict]:
    return _answer(store.issues.list_issues, agent_id)


@router.post("/issues", status_code=201, response_model=Issue, responses=_MISSING | _REFUSED)
def report_issue(agent_id: str, body: IssueReport) -> dict:
    """Report an issue by hand, numbered like the rest: "Issue #14".

    Left without a title, it gets one Prosper AI writes from what happened.
    """
    return _answer(
        tidy.report,
        agent_id,
        body.title.strip(),
        body.description.strip(),
        body.step,
        body.severity,
        body.reported,
        body.calls,
        YOU,
    )


@router.patch("/issues/{number}", response_model=Issue, responses=_MISSING | _REFUSED)
def edit_issue(agent_id: str, number: int, body: IssueEdit) -> dict:
    """Change a reported issue's words, step or severity, and link calls to it."""
    sent = body.model_fields_set - {"calls", "tidied"}
    changes = {key: getattr(body, key) for key in sent}
    if changes.get("step") is None:
        changes.pop("step", None)  # null leaves it; "" is "not sure"
    by = store.PROSPER if body.tidied else YOU
    return _answer(store.issues.edit, agent_id, number, changes, body.calls, by)


@router.post(
    "/issues/{number}/tidy", response_model=Tidied, responses=_MISSING | _REFUSED | {502: {}}
)
def tidy_issue(agent_id: str, number: int) -> dict:
    """Prosper AI's plain title, step, severity and calls for a reported issue, to keep or not."""
    _agent(agent_id)
    try:
        return _answer(tidy.tidy, agent_id, number)
    except Failed as error:
        detail = f"Prosper AI couldn't tidy it: {error}"
        raise HTTPException(status_code=502, detail=detail) from error


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


@router.post(
    "/issues/{number}/fix", status_code=201, response_model=Pull, responses=_MISSING | _REFUSED
)
def fix(agent_id: str, number: int, body: Fix) -> dict:
    """Open a pull request that fixes the issue, on a copy of live: "Fix: <its title>".

    With Prosper AI, it opens it and starts on it at once, with the fix brief.
    """
    if not body.prosper:
        return _answer(store.open_fix, agent_id, number, YOU)
    work = {"state": "working", "doing": "Reading the issue and its calls", "questions": []}
    pull = _answer(store.open_fix, agent_id, number, store.PROSPER, work)
    agent.start(agent_id, pull["number"])
    return pull
