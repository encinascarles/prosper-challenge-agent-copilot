#
# Versions and pull requests API — what an agent's callers get, and the
# proposed changes to it.
#
# The editor never writes to a version: it opens a pull request, saves to that
# pull request's copy, and merges it, which adds the next version and makes it
# live. Each step that is refused says why: 404 when there is no such thing,
# 409 when the state forbids it (a merged pull request, a stale base), 422 with
# the located problem when the copy is not an agent the bot could run.
#
# A copy also carries its rules and tests (suite.py has their routes), and each
# change to a pull request's copy starts its checks again (checks.py). A merge
# is refused (409) until they have passed on the copy as it is.
#
# A pull request left behind by a merge is updated by sending its changes
# replayed on the new live version. The replay is worked out by the client
# (frontend/src/pulls/diff.ts), which already compares versions to show what a
# pull request changes; this side checks the result is an agent and that live
# is still the version it was replayed on.
#

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints, model_serializer

import store

from . import checks
from .models import INVALID, YOU, AgentSave, Position, Problem, not_found, problem

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["versions and pull requests"])


class Before(BaseModel):
    """How the test that reproduces an issue went on the version that had it."""

    version: int
    passed: int  # of `runs` calls
    runs: int


class Source(BaseModel):
    # manual: written by hand. Prosper AI's: from a line of the guidelines, from
    # the person's answer to its question, or from something they asked for.
    # check: added by Prosper AI when it checked its own draft against a failing test.
    # issue: added by Prosper AI fixing an issue: the test that reproduces it,
    # or the rule that fixes it.
    kind: Literal["manual", "guidelines", "answer", "request", "check", "issue"]
    pull: int | None = None  # the pull request it was added in
    file: str | None = None  # guidelines: the file it quotes, or "your notes"
    quote: str | None = None  # the line it comes from, or the answer or request, word for word
    issue: int | None = None  # issue: the issue's number
    before: Before | None = None  # issue, a test: how it went on the version with the issue

    @model_serializer(mode="wrap")
    def _only_for_issues(self, handler):
        # Left out rather than null where they mean nothing: every other source.
        data = handler(self)
        for key in ("issue", "before"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class Rule(BaseModel):
    id: str
    step: str | None  # the step (node name) it is for; None for every step
    text: str
    source: Source


class Test(BaseModel):
    id: str
    name: str
    caller: str  # who calls and what they want
    checks: list[str]  # one line each
    source: Source


class Checks(BaseModel):
    """How the latest run of a copy's tests is going."""

    state: Literal["running", "passed", "failed", "stopped"]
    passed: int  # tests that passed every one of their runs
    flaky: int  # tests that passed all their runs but one: shown, not in the way of a merge
    failing: int  # tests that failed more than one run: these block a merge
    total: int


class VersionSummary(BaseModel):
    number: int
    pull: int | None  # the pull request it was merged from; None if it predates them
    title: str | None  # that pull request's title
    created_at: str


class Version(BaseModel):
    number: int
    pull: int | None
    config: dict[str, Any]  # the agent JSON, as agent_builder/schema.py defines it
    layout: dict[str, Position]  # where the editor drew each node, by node name
    rules: list[Rule]
    tests: list[Test]
    created_at: str


class FileRead(BaseModel):
    name: str
    kind: str  # PDF, DOCX, TXT, MD
    pages: int | None  # a PDF's


class PullEvent(BaseModel):
    type: Literal[
        "opened",
        "saved",
        "merged",
        "closed",
        "reopened",
        "updated",
        "rule",
        "test",
        "checks",
        # Prosper AI's conversation: what it was asked (notes and files), each
        # step it finished, its questions and their answers, and messages.
        "request",
        "step",
        "question",
        "answer",
        "message",
        "interrupted",  # Prosper AI's work stopped with the server; a message retries it
        # Fixing an issue: the test that reproduces it, the change it proposes,
        # and the checks passing with it.
        "reproduced",
        "proposed",
        "proved",
    ]
    by: str  # "you", "Prosper AI", or "checks" for a run of the tests
    at: str
    # "opened": the version it was copied from; "merged": the version it became;
    # "updated": its new base.
    version: int | None = None
    summary: str | None = None  # "saved", "updated": one line on what changed
    # "rule": its step (None for every step) and text; "test": its name, as text.
    step: str | None = None
    text: str | None = None
    removed: bool | None = None  # the rule or test was taken out
    passed: int | None = None  # "checks": the tests that passed, of `total`
    flaky: int | None = None  # "checks": the tests that passed all their runs but one
    total: int | None = None
    # "request": the pasted notes and the files read. "step", "message": `text`.
    notes: str | None = None
    files: list[FileRead] | None = None
    question: str | None = None  # "question", "answer": the question's id
    options: list[str] | None = None  # "question": what can be picked
    changed: bool | None = None  # "message": Prosper AI changed the agent with it
    details: list[str] | None = None  # "message": one line per thing it decided, folded under it
    rewritten: bool | None = None  # "test": Prosper AI rewrote it, `why` says why
    why: str | None = None
    issue: int | None = None  # "opened": the issue a fix is for
    test: str | None = None  # "reproduced", "proved": the id of the test that reproduces it


class Prosper(BaseModel):
    """What Prosper AI is up to on a pull request it works on."""

    state: Literal["working", "waiting", "done", "failed"]  # waiting: for an answer
    doing: str | None  # while working: the step under way
    usage: dict[str, float] | None  # requests, tokens and USD spent so far


class PullSummary(BaseModel):
    number: int  # per agent: shown as "PR #3"
    title: str
    # setup: pull request #1 of a new agent; fix: opened from an issue, to fix it
    kind: Literal["setup", "edit", "fix"]
    state: Literal["open", "merged", "closed"]
    base_version: int  # the live version it was copied from; 0 for a setup
    merged_version: int | None  # the version it became, once merged
    fixes: int | None  # a fix: the number of the issue it fixes
    created_at: str
    updated_at: str
    checks: Checks | None  # its latest run of the tests; None if none ran
    prosper: Prosper | None  # Prosper AI's work on it; None if it has no part in it


class Pull(PullSummary):
    config: dict[str, Any]  # its own copy of the agent
    layout: dict[str, Position]
    rules: list[Rule]
    tests: list[Test]
    events: list[PullEvent]


class PullOpen(BaseModel):
    title: str = Field(min_length=1, examples=["Your edits"])
    # Only edits are opened this way: a setup comes with a new agent, and a
    # fix is opened from its issue.
    kind: Literal["edit"] = "edit"


class PullSave(AgentSave):
    summary: str | None = Field(
        default=None,
        description="One line on what this save changes, for the pull request's log.",
        examples=["Edited Confirm · added Waitlist"],
    )
    renames: dict[str, str] | None = Field(
        default=None,
        description="Steps this save renames, old name to new: their rules follow them.",
        examples=[{"confirm": "confirm_booking"}],
    )


class PullRename(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        examples=["Ask for the date of birth first"]
    )


class PullUpdate(PullSave):
    onto: int = Field(description="The live version `config` was replayed on.", examples=[2])


_MISSING = {404: {"model": Problem, "description": "No such agent, version or pull request."}}
_REFUSED = {409: {"model": Problem, "description": "Not in the state this needs; says why."}}


def _answer(action, *args) -> dict:
    """Run a store change, turning what it refuses into the HTTP error that says why."""
    try:
        return action(*args)
    except store.NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except store.Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _agent(agent_id: str) -> dict:
    record = store.get_agent(agent_id)
    if record is None:
        raise not_found(agent_id)
    return record


@router.get("/versions", response_model=list[VersionSummary], responses=_MISSING)
def list_versions(agent_id: str) -> list[dict]:
    _agent(agent_id)
    return store.list_versions(agent_id)


@router.get("/versions/{number}", response_model=Version, responses=_MISSING)
def get_version(agent_id: str, number: int) -> dict:
    _agent(agent_id)
    version = store.get_version(agent_id, number)
    if version is None:
        raise HTTPException(status_code=404, detail=f"The agent has no v{number}.")
    return version


@router.get("/pulls", response_model=list[PullSummary], responses=_MISSING)
def list_pulls(
    agent_id: str, state: Literal["open", "merged", "closed"] | None = None
) -> list[dict]:
    _agent(agent_id)
    return store.list_pulls(agent_id, state)


@router.post("/pulls", status_code=201, response_model=Pull, responses=_MISSING | _REFUSED)
def open_pull(agent_id: str, body: PullOpen) -> dict:
    # On a copy of live. Before the agent is live there is nothing to copy,
    # and its changes belong on pull request #1.
    return _answer(store.open_pull, agent_id, body.title, body.kind, YOU)


@router.get("/pulls/{number}", response_model=Pull, responses=_MISSING)
def get_pull(agent_id: str, number: int) -> dict:
    _agent(agent_id)
    pull = store.get_pull(agent_id, number)
    if pull is None:
        raise HTTPException(status_code=404, detail=f"The agent has no {store.label(number)}.")
    return pull


@router.put("/pulls/{number}", response_model=Pull, responses=_MISSING | _REFUSED | INVALID)
def save_pull(agent_id: str, number: int, save: PullSave) -> Any:
    # Replaces the whole copy: the editor always holds the full graph, and a
    # partial update could leave edges pointing at nodes that are gone.
    if found := problem(save.config):
        return found
    _answer(
        store.save_pull,
        agent_id,
        number,
        save.config,
        save.positions(),
        YOU,
        save.summary,
        save.renames,
    )
    checks.start(agent_id, pull=number)
    return store.get_pull(agent_id, number)


@router.patch("/pulls/{number}", response_model=Pull, responses=_MISSING | _REFUSED)
def rename_pull(agent_id: str, number: int, body: PullRename) -> dict:
    return _answer(store.rename_pull, agent_id, number, body.title)


@router.post("/pulls/{number}/merge", response_model=Pull, responses=_MISSING | _REFUSED | INVALID)
def merge_pull(agent_id: str, number: int) -> Any:
    # The copy was valid when it was saved; it is checked again because what
    # goes live must pass the rules as they are now, not as they were then.
    pull = get_pull(agent_id, number)
    # Prosper AI first: before its answers are in there may be no agent at all,
    # and "the agent has no nodes" would not say why.
    if reason := store.busy(pull, merging=True):
        raise HTTPException(status_code=409, detail=reason)
    if found := problem(pull["config"]):
        return found
    return _answer(store.merge_pull, agent_id, number, YOU)


@router.post("/pulls/{number}/close", response_model=Pull, responses=_MISSING | _REFUSED)
def close_pull(agent_id: str, number: int) -> dict:
    return _answer(store.close_pull, agent_id, number, YOU)


@router.post("/pulls/{number}/reopen", response_model=Pull, responses=_MISSING | _REFUSED)
def reopen_pull(agent_id: str, number: int) -> dict:
    return _answer(store.reopen_pull, agent_id, number, YOU)


@router.post(
    "/pulls/{number}/update", response_model=Pull, responses=_MISSING | _REFUSED | INVALID
)
def update_pull(agent_id: str, number: int, update: PullUpdate) -> Any:
    if found := problem(update.config):
        return found
    # A copy always has a layout; one left out keeps no positions, and the
    # editor places those cards again.
    layout = update.positions() or {}
    _answer(
        store.update_pull,
        agent_id,
        number,
        update.config,
        layout,
        update.onto,
        YOU,
        update.summary,
    )
    checks.start(agent_id, pull=number)
    return store.get_pull(agent_id, number)
