#
# Calls — which agent a call runs.
#
# A call is started with the id of a saved agent, `{ "agent_id": "<id>" }`, in
# the body the Pipecat runner hands to the bot. The call runs that agent's live
# version, what its callers get: what is tested is what was saved, never a
# draft that only exists in a browser.
#
# A test call can try a pull request before it is merged instead:
# `{ "agent_id": "<id>", "pull": 5 }` runs that pull request's saved copy. Only
# an open one: a merged pull request is a version now, and a closed one is not
# going anywhere. Production calls never name a pull request.
#
# A start that names no agent runs the sample flow. That is what Pipecat's
# prebuilt client at /client sends, and it keeps that page working with no
# agent to pick.
#
# A call started for a saved agent is a test call: a person trying it from
# Build. It is recorded (`TestCallRecord`) and stored when it ends, apart from
# the calls callers make (store/test_calls.py). The voice pipeline only hands
# the record what it hears: each node the call enters, and each finished turn
# of either side.
#
# The runner owns POST /start and, for WebRTC, only files the body away: the bot
# starts later, when the browser's offer arrives, and by then the caller has
# been told the call started. So the same check also runs in front of /start
# (`check_start`), where a wrong id is still an HTTP error the caller can read.
#

import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

import store
from agent_builder import AgentBuilder
from store.db import now

from .models import YOU

SAMPLE_FLOW = Path(__file__).parent.parent / "example_flow.json"


class CallError(ValueError):
    """Why a call cannot start, as a sentence for whoever asked, and its HTTP status."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def agent_for_call(body: Any) -> AgentBuilder:
    """The agent a call started with `body` runs, compiled and ready.

    Raises CallError if the body names an agent that cannot be run.
    """
    # No body arrives as None or {} depending on the route the client took.
    if not isinstance(body, dict) or "agent_id" not in body:
        return AgentBuilder.from_json(SAMPLE_FLOW)
    agent_id = body["agent_id"]
    # An id that is there but empty is a client that lost it, not a request for
    # the sample: running another agent in silence would be the worse answer.
    if not isinstance(agent_id, str) or not agent_id:
        raise CallError("'agent_id' must be the id of a saved agent.", status=422)
    record = store.get_agent(agent_id)
    if record is None:
        raise CallError(f"No agent with id '{agent_id}'.", status=404)
    if "pull" in body:
        copy = _pull_copy(agent_id, body["pull"])
    elif record["live_version"] == 0:
        raise CallError(f"{record['name']} is not live yet: merge PR #1 first.", status=409)
    else:
        copy = store.get_version(agent_id, record["live_version"])
    try:
        # With its rules: they are part of what the agent is told.
        return AgentBuilder.from_dict(copy["config"], copy["rules"])
    except ValueError as error:
        # Every stored agent passed this check when it was saved, so this is an
        # agent saved before a rule existed. Say which rule.
        raise CallError(f"Agent '{agent_id}' cannot run: {error}", status=422) from error


def _pull_copy(agent_id: str, number: Any) -> dict:
    """The saved copy of the agent's open pull request `number`."""
    # bool is an int to Python, and `true` is not a pull request number.
    if not isinstance(number, int) or isinstance(number, bool):
        raise CallError("'pull' must be the number of a pull request.", status=422)
    pull = store.get_pull(agent_id, number)
    if pull is None:
        raise CallError(f"The agent has no {store.label(number)}.", status=404)
    if pull["state"] != "open":
        raise CallError(f"{store.label(number)} is {pull['state']}.", status=409)
    return pull


class TestCallRecord:
    """What a test call did, as it goes, and stored once it is over."""

    def __init__(self, agent_id: str, pull: Optional[int], version: Optional[int], ends: set):
        self.agent_id = agent_id
        self.pull = pull
        self.version = version
        self.path: list[dict] = []  # { node, from, edge, collected }, as the browser is told
        self.transcript: list[dict] = []  # { role: "agent" | "caller", text, node }
        self._ends = ends  # the names of the agent's end nodes
        self._at: Optional[str] = None
        self._started = 0.0

    def started(self) -> None:
        """The caller is on the line: the call's time starts."""
        self._at = now()
        self._started = time.monotonic()

    def entered(self, message: dict) -> None:
        self.path.append({key: message[key] for key in ("node", "from", "edge", "collected")})

    def said(self, role: str, text: Optional[str]) -> None:
        # A turn that only moved the call on (a function call) said nothing.
        if text and text.strip():
            node = self.path[-1]["node"] if self.path else None
            self.transcript.append({"role": role, "text": text.strip(), "node": node})

    def listen(self, aggregator: LLMContextAggregatorPair) -> None:
        """Take each finished turn, heard or said, from the pipeline's context aggregators."""

        @aggregator.user().event_handler("on_user_turn_message_added")
        async def on_caller(_, message):
            self.said("caller", message.content)

        @aggregator.assistant().event_handler("on_assistant_turn_stopped")
        async def on_agent(_, message):
            self.said("agent", message.content)

    def save(self) -> Optional[int]:
        """Store the call. Returns its id; None for a call nobody joined. Never raises."""
        if self._at is None:
            return None
        last = self.path[-1]["node"] if self.path else None
        try:
            return store.test_calls.add_test_call(
                self.agent_id,
                self.pull,
                self.version,
                YOU,  # placed from the builder, by the person using it: there are no accounts
                self._at,
                round(time.monotonic() - self._started),
                "agent_ended" if last in self._ends else "caller_hung_up",
                self.path,
                self.transcript,
            )
        except Exception:  # noqa: BLE001 - the call happened either way; losing its record is not a crash
            logger.exception(f"The test call on agent {self.agent_id} was not stored")
            return None


def record_for(body: Any, builder: AgentBuilder) -> Optional[TestCallRecord]:
    """The record of a call started with `body`, which runs `builder`; None for the sample."""
    if not isinstance(body, dict) or "agent_id" not in body:
        return None  # Pipecat's prebuilt client: not an agent of the builder
    ends = {node.name for node in builder.config.nodes if node.end}
    if "pull" in body:
        return TestCallRecord(body["agent_id"], body["pull"], None, ends)
    record = store.get_agent(body["agent_id"])
    return TestCallRecord(body["agent_id"], None, record["live_version"] if record else None, ends)


def describe(body: Any) -> str:
    """What a call started with `body` runs, for the log."""
    if not isinstance(body, dict) or "agent_id" not in body:
        return "the sample flow"
    if "pull" in body:
        return f"agent {body['agent_id']}, PR #{body['pull']}"
    return f"agent {body['agent_id']}, live"


async def check_start(request: Request, call_next):
    """HTTP middleware: refuse a POST /start whose body names an agent that cannot run."""
    if request.method == "POST" and request.url.path == "/start":
        try:
            # Starlette keeps the body it read here for the route behind.
            start = json.loads(await request.body() or b"{}")
        except ValueError:
            start = {}  # the runner treats an unreadable body as an empty one
        if isinstance(start, dict):
            try:
                # sqlite3 blocks, but for one row by primary key, once per call.
                agent_for_call(start.get("body"))
            except CallError as error:
                return JSONResponse(status_code=error.status, content={"detail": str(error)})
    return await call_next(request)
