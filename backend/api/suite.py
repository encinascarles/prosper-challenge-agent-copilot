#
# Rules, tests and checks API — what an agent must do, and whether it does.
#
# Rules and tests are added to a pull request's copy one at a time, and taken
# out again only in the pull request that added them; live is never written
# to. Each change answers with the pull request, and starts its checks again
# (checks.py). The checks of a copy are its latest run, read here while it
# runs; a version's checks can also be run again by hand, and any copy's
# tests one at a time.
#

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

import store

from . import checks
from .models import YOU
from .pulls import _MISSING, _REFUSED, Pull, _agent, _answer, get_pull

router = APIRouter(prefix="/api/agents/{agent_id}", tags=["rules, tests and checks"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RuleAdd(BaseModel):
    step: str | None = Field(
        default=None, description="The step (node name) it is for; null for every step."
    )
    text: Text = Field(examples=["Never give medical advice."])


class TestAdd(BaseModel):
    name: Text = Field(examples=["Asks for a home visit"])
    caller: Text = Field(
        description="Who calls and what they want, as the simulated caller will play it.",
        examples=["Lisa wants a home visit for her mother, who cannot travel."],
    )
    checks: list[str] = Field(
        description=(
            "What must happen, one per line. 'Reaches <step>', 'Ends the call' and "
            "'<field> is recorded' are decided from the call's path; anything else is judged."
        ),
        examples=[["Says the clinic does no home visits", "Ends the call"]],
    )

    @field_validator("checks")
    @classmethod
    def _lines(cls, lines: list[str]) -> list[str]:
        lines = [line.strip() for line in lines if line.strip()]
        if not lines:
            raise ValueError("A test needs at least one check.")
        return lines


class CheckResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    text: str
    kind: Literal["reaches", "ends", "recorded", "judged"]
    passed: bool = Field(alias="pass")
    detail: str | None  # why it failed, the value recorded, or the judge's reason


class PathStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    node: str
    came_from: str | None = Field(alias="from")
    edge: str | None
    collected: dict[str, Any]


class Line(BaseModel):
    role: Literal["agent", "caller"]
    text: str
    node: str | None


class TestCall(BaseModel):
    """One of a test's simulated calls, checked."""

    passed: bool
    ended: str  # agent_ended, caller_hung_up, turn_cap, stuck, end_not_reached or error
    seconds: float
    tokens: dict[str, dict[str, int]]  # by who used them: agent, caller, judge
    path: list[PathStep]
    transcript: list[Line]
    checks: list[CheckResult]


class TestRun(BaseModel):
    id: str
    name: str
    runs: list[TestCall]  # as they finish, up to the run's `repeats`


class SuiteRun(BaseModel):
    id: int
    pull: int | None
    version: int | None
    state: Literal["running", "done", "stopped"]
    # Of the config, rules and tests it ran on; None for a run from before fingerprints.
    fingerprint: str | None
    repeats: int
    tests: list[TestRun]
    started_at: str
    finished_at: str | None


class OneTestRun(SuiteRun):
    """The run one test was run again in."""

    # Why it ran alone, in a run of its own, rather than into the latest run;
    # null when it went into it and the others' results still stand.
    alone: str | None


def _changed(agent_id: str, number: int, change, *args) -> dict:
    _answer(change, agent_id, number, *args)
    checks.start(agent_id, pull=number)
    return store.get_pull(agent_id, number)


@router.post("/pulls/{number}/rules", response_model=Pull, responses=_MISSING | _REFUSED)
def add_rule(agent_id: str, number: int, rule: RuleAdd) -> dict:
    return _changed(agent_id, number, store.add_rule, rule.step, rule.text, YOU)


@router.delete(
    "/pulls/{number}/rules/{rule_id}", response_model=Pull, responses=_MISSING | _REFUSED
)
def take_out_rule(agent_id: str, number: int, rule_id: str) -> dict:
    return _changed(agent_id, number, store.take_out, "rules", rule_id, YOU)


@router.post("/pulls/{number}/tests", response_model=Pull, responses=_MISSING | _REFUSED)
def add_test(agent_id: str, number: int, test: TestAdd) -> dict:
    return _changed(agent_id, number, store.add_test, test.model_dump(), YOU)


@router.delete(
    "/pulls/{number}/tests/{test_id}", response_model=Pull, responses=_MISSING | _REFUSED
)
def take_out_test(agent_id: str, number: int, test_id: str) -> dict:
    return _changed(agent_id, number, store.take_out, "tests", test_id, YOU)


@router.get("/pulls/{number}/checks", response_model=SuiteRun | None, responses=_MISSING)
def pull_checks(agent_id: str, number: int) -> dict | None:
    """The latest run of the pull request's tests, finished or not; null if none ran."""
    get_pull(agent_id, number)
    return store.get_run(agent_id, pull=number)


@router.post("/pulls/{number}/checks", response_model=SuiteRun, responses=_MISSING | _REFUSED)
def run_pull_checks(agent_id: str, number: int) -> dict:
    pull = get_pull(agent_id, number)
    if pull["state"] != "open":
        raise HTTPException(status_code=409, detail=f"{store.label(number)} is {pull['state']}.")
    return checks.start(agent_id, pull=number, again=True)


@router.post(
    "/pulls/{number}/checks/{test_id}", response_model=OneTestRun, responses=_MISSING | _REFUSED
)
def run_pull_test(agent_id: str, number: int, test_id: str) -> dict:
    """Run one test of the pull request's copy again, 3 times, leaving the others' results."""
    pull = get_pull(agent_id, number)
    if pull["state"] != "open":
        raise HTTPException(status_code=409, detail=f"{store.label(number)} is {pull['state']}.")
    run, alone = _answer(checks.start_test, agent_id, test_id, number, None)
    return {**run, "alone": alone}


@router.get("/versions/{number}/checks", response_model=SuiteRun | None, responses=_MISSING)
def version_checks(agent_id: str, number: int) -> dict | None:
    """The latest run of the version's tests: run on it, or on the pull request it came from."""
    _version(agent_id, number)
    return store.get_run(agent_id, version=number)


@router.post("/versions/{number}/checks", response_model=SuiteRun, responses=_MISSING)
def run_version_checks(agent_id: str, number: int) -> dict:
    _version(agent_id, number)
    return checks.start(agent_id, version=number, again=True)


@router.post(
    "/versions/{number}/checks/{test_id}",
    response_model=OneTestRun,
    responses=_MISSING | _REFUSED,
)
def run_version_test(agent_id: str, number: int, test_id: str) -> dict:
    """Run one test of the version again, 3 times, leaving the others' results."""
    _version(agent_id, number)
    run, alone = _answer(checks.start_test, agent_id, test_id, None, number)
    return {**run, "alone": alone}


def _version(agent_id: str, number: int) -> None:
    _agent(agent_id)
    if store.get_version(agent_id, number) is None:
        raise HTTPException(status_code=404, detail=f"The agent has no v{number}.")
