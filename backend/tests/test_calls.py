#
# Starting a call, with no call: no WebRTC, no OpenAI and no ElevenLabs.
#
# A call runs the saved agent it was started for, a start that names none runs
# the sample (Pipecat's prebuilt client), and a wrong id is refused while it is
# still an HTTP error: in front of the runner's /start, before there is a call.
#

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request

import api
import bot
from agent_builder import AgentBuilder


def _saved(client, agent, name="Saved agent") -> str:
    """The id of a saved agent that is not the sample, told apart by its name."""
    agent["name"] = name
    return client.post("/api/agents", json={"config": agent}).json()["id"]


def _sample_name() -> str:
    return AgentBuilder.from_json(api.calls.SAMPLE_FLOW).config.name


# ---- which agent a call runs -------------------------------------------------


def test_a_call_runs_the_saved_agent_it_names(client, agent):
    builder = api.agent_for_call({"agent_id": _saved(client, agent)})

    assert builder.config.name == "Saved agent"


@pytest.mark.parametrize("body", [None, {}, {"other": 1}], ids=["none", "empty", "no id"])
def test_a_call_that_names_no_agent_runs_the_sample(client, agent, body):
    _saved(client, agent)

    assert api.agent_for_call(body).config.name == _sample_name()


def test_an_unknown_agent_is_refused(client):
    with pytest.raises(api.CallError, match="No agent with id 'nope'.") as refused:
        api.agent_for_call({"agent_id": "nope"})

    assert refused.value.status == 404


@pytest.mark.parametrize("agent_id", [None, "", 7], ids=["null", "empty", "number"])
def test_an_id_that_is_not_one_is_refused_instead_of_running_the_sample(client, agent_id):
    with pytest.raises(api.CallError, match="'agent_id' must be the id of a saved agent.") as r:
        api.agent_for_call({"agent_id": agent_id})

    assert r.value.status == 422


# ---- POST /start, in front of the runner's own route ---------------------------


@pytest.fixture
def start(client):
    """The runner's /start, stood in for by a route that says what body reached it."""

    @client.app.post("/start")
    async def runner_start(request: Request):
        return {"reached": await request.json()}

    return lambda **kwargs: client.post("/start", **kwargs)


def test_start_with_a_saved_agent_reaches_the_runner_with_its_body(client, agent, start):
    request = {"body": {"agent_id": _saved(client, agent)}, "enableDefaultIceServers": True}

    response = start(json=request)

    assert (response.status_code, response.json()) == (200, {"reached": request})


def test_start_with_an_unknown_agent_fails_before_the_runner(start):
    response = start(json={"body": {"agent_id": "nope"}})

    assert (response.status_code, response.json()) == (404, {"detail": "No agent with id 'nope'."})


def test_start_with_an_empty_agent_id_fails_before_the_runner(start):
    response = start(json={"body": {"agent_id": ""}})

    assert response.status_code == 422
    assert response.json() == {"detail": "'agent_id' must be the id of a saved agent."}


@pytest.mark.parametrize(
    "request_json", [{}, {"body": {}}, {"enableDefaultIceServers": True}], ids=str
)
def test_start_without_an_agent_goes_through(start, request_json):
    # What Pipecat's prebuilt client sends.
    assert start(json=request_json).json() == {"reached": request_json}


def test_other_routes_are_not_read_as_a_start(client):
    assert client.post("/api/agents", json={"body": {"agent_id": "nope"}}).status_code == 422
    assert client.get("/api/agents").status_code == 200


# ---- the bot's entry point ----------------------------------------------------


@pytest.fixture
def ran(monkeypatch):
    """bot() with the voice pipeline cut off: the builders it would have run."""
    builders = []

    async def run_bot(transport, runner_args, builder):
        builders.append(builder)

    monkeypatch.setattr(bot, "run_bot", run_bot)
    monkeypatch.setattr(bot, "create_transport", AsyncMock())
    return builders


def test_the_bot_runs_the_agent_in_the_start_body(client, agent, ran):
    agent_id = _saved(client, agent)

    asyncio.run(bot.bot(SimpleNamespace(body={"agent_id": agent_id})))

    assert [builder.config.name for builder in ran] == ["Saved agent"]


def test_the_bot_runs_the_sample_without_a_body(client, ran):
    asyncio.run(bot.bot(SimpleNamespace(body=None)))

    assert [builder.config.name for builder in ran] == [_sample_name()]


def test_the_bot_hangs_up_on_an_unknown_agent(client, ran):
    connection = SimpleNamespace(disconnect=AsyncMock())

    asyncio.run(bot.bot(SimpleNamespace(body={"agent_id": "nope"}, webrtc_connection=connection)))

    assert ran == []
    connection.disconnect.assert_awaited_once()
