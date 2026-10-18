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
# A pull request left behind by a merge is updated by sending its changes
# replayed on the new live version. The replay is worked out by the client
# (frontend/src/pulls/diff.ts), which already compares versions to show what a
# pull request changes; this side checks the result is an agent and that live
# is still the version it was replayed on.
#

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

import store

from .models import INVALID, YOU, AgentSave, Position, Problem, not_found, problem

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["versions and pull requests"])


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
    created_at: str


class PullEvent(BaseModel):
    type: Literal["opened", "saved", "merged", "closed", "reopened", "updated"]
    by: str  # "you" for now; Prosper's own changes will carry its name
    at: str
    version: int | None = None  # "merged": the version it became; "updated": its new base
    summary: str | None = None  # "saved", "updated": one line on what changed


class PullSummary(BaseModel):
    number: int  # per agent: shown as "PR #3"
    title: str
    kind: Literal["setup", "edit"]  # setup: pull request #1 of a new agent
    state: Literal["open", "merged", "closed"]
    base_version: int  # the live version it was copied from; 0 for a setup
    merged_version: int | None  # the version it became, once merged
    created_at: str
    updated_at: str


class Pull(PullSummary):
    config: dict[str, Any]  # its own copy of the agent
    layout: dict[str, Position]
    events: list[PullEvent]


class PullOpen(BaseModel):
    title: str = Field(min_length=1, examples=["Your edits"])
    # Only edits are opened this way: a setup comes with a new agent, and the
    # kinds Prosper will open (fixes) come with it.
    kind: Literal["edit"] = "edit"


class PullSave(AgentSave):
    summary: str | None = Field(
        default=None,
        description="One line on what this save changes, for the pull request's log.",
        examples=["Edited Confirm · added Waitlist"],
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
    return _answer(
        store.save_pull, agent_id, number, save.config, save.positions(), YOU, save.summary
    )


@router.patch("/pulls/{number}", response_model=Pull, responses=_MISSING | _REFUSED)
def rename_pull(agent_id: str, number: int, body: PullRename) -> dict:
    return _answer(store.rename_pull, agent_id, number, body.title)


@router.post("/pulls/{number}/merge", response_model=Pull, responses=_MISSING | _REFUSED | INVALID)
def merge_pull(agent_id: str, number: int) -> Any:
    # The copy was valid when it was saved; it is checked again because what
    # goes live must pass the rules as they are now, not as they were then.
    pull = get_pull(agent_id, number)
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
    return _answer(
        store.update_pull,
        agent_id,
        number,
        update.config,
        layout,
        update.onto,
        YOU,
        update.summary,
    )
