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
# The runner owns POST /start and, for WebRTC, only files the body away: the bot
# starts later, when the browser's offer arrives, and by then the caller has
# been told the call started. So the same check also runs in front of /start
# (`check_start`), where a wrong id is still an HTTP error the caller can read.
#

import json
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

import store
from agent_builder import AgentBuilder

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
