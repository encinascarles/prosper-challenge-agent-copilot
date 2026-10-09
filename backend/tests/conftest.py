#
# Shared fixtures. Tests never touch the real database, the network or an LLM:
# the store points at a temp file and the API runs on a bare FastAPI app, with
# no Pipecat runner and no voice pipeline behind it.
#

import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api
import store
from store.agents import DB_PATH_ENV

EXAMPLE_FLOW = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())


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
