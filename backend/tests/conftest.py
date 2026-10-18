#
# Shared fixtures. Tests never touch the real database, the network or an LLM:
# the store points at a temp file and the API runs on a bare FastAPI app, with
# no Pipecat runner and no voice pipeline behind it. The checks every change
# starts run on fakes (tests/fakes.py), and each test waits for them to end
# before its database goes away.
#

import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api
import store
from api import checks
from copilot import setup
from store.db import DB_PATH_ENV
from tests.fakes import FakeServices, ScriptedModel

EXAMPLE_FLOW = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())


@pytest.fixture(autouse=True)
def fake_checks(monkeypatch) -> FakeServices:
    """What the checks talk to, in every test: never OpenAI."""
    services = FakeServices()
    monkeypatch.setattr(checks, "services", services)
    yield services
    checks.wait()


@pytest.fixture(autouse=True)
def prosper_model(monkeypatch) -> ScriptedModel:
    """Prosper AI's model, in every test: scripted, empty until a test scripts it."""
    model = ScriptedModel({})
    monkeypatch.setattr(setup, "new_llm", lambda: model)
    yield model
    setup.wait()
    checks.wait()


@pytest.fixture
def agent() -> dict:
    """A valid agent each test can break in its own way."""
    return copy.deepcopy(EXAMPLE_FLOW)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """The agents API over a fresh, seeded database."""
    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path / "agents.db"))
    store.init_db()
    app = FastAPI()
    api.mount(app)
    return TestClient(app)


@pytest.fixture
def new_agent(client, agent):
    """Create an agent through the API, named `name`: its id and its pull request #1."""

    def create(name: str = "Dental Recall", layout: dict | None = None) -> tuple[str, dict]:
        body = {"config": {**agent, "name": name}}
        if layout is not None:
            body["layout"] = layout
        created = client.post("/api/agents", json=body).json()
        return created["agent"]["id"], created["pull"]

    return create


@pytest.fixture
def live_agent(client, new_agent):
    """Create an agent and merge its pull request #1, so it is live as v1. Returns its id."""

    def create(name: str = "Dental Recall") -> str:
        agent_id, _ = new_agent(name)
        assert client.post(f"/api/agents/{agent_id}/pulls/1/merge").status_code == 200
        return agent_id

    return create
