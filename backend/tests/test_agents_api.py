#
# The agents API end to end: HTTP in, SQLite on a temp file, HTTP out.
#
# These go through the real router, AgentBuilder and store, so they cover the
# promise the editor relies on: whatever the API stored is an agent that runs,
# and a rejected save changes nothing.
#

import json
import sqlite3

import pytest

import store
from store import agents as agent_store


def _seeded_id(client) -> str:
    return client.get("/api/agents").json()[0]["id"]


def test_list_starts_with_the_seeded_example(client, agent):
    response = client.get("/api/agents")

    assert response.status_code == 200
    [summary] = response.json()
    assert set(summary) == {"id", "name", "nodes", "updated_at"}
    assert (summary["name"], summary["nodes"]) == (agent["name"], len(agent["nodes"]))


def test_init_db_seeds_only_an_empty_table(client):
    store.init_db()  # what a server restart does

    assert len(client.get("/api/agents").json()) == 1


def test_a_broken_seed_is_refused_and_not_stored(tmp_path, monkeypatch, agent):
    agent["nodes"][0]["edges"][0]["target"] = "x"
    broken = tmp_path / "broken_flow.json"
    broken.write_text(json.dumps(agent))
    monkeypatch.setenv(agent_store.DB_PATH_ENV, str(tmp_path / "empty.db"))
    monkeypatch.setattr(agent_store, "SEED_FLOW", broken)

    with pytest.raises(ValueError, match="targets unknown node 'x'"):
        store.init_db()
    assert store.list_agents() == []


def test_get_returns_the_full_agent(client, agent):
    response = client.get(f"/api/agents/{_seeded_id(client)}")

    assert response.status_code == 200
    record = response.json()
    assert set(record) == {"id", "config", "created_at", "updated_at"}
    assert record["config"] == agent


def test_get_unknown_id_is_404(client):
    response = client.get("/api/agents/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_create_stores_the_agent_and_returns_its_record(client, agent):
    agent["name"] = "Dental Recall"

    response = client.post("/api/agents", json=agent)

    assert response.status_code == 201
    record = response.json()
    assert record["config"] == agent
    assert record["created_at"] == record["updated_at"]
    assert client.get(f"/api/agents/{record['id']}").json() == record
    assert [a["name"] for a in client.get("/api/agents").json()] == [
        "Prosper Scheduler",
        "Dental Recall",
    ]


def test_update_replaces_the_agent(client, agent):
    created = client.post("/api/agents", json=agent).json()
    agent["name"] = "Renamed"
    agent["nodes"] = agent["nodes"][-1:]  # the terminal node alone is a valid graph
    agent["initial_node"] = agent["nodes"][0]["name"]

    response = client.put(f"/api/agents/{created['id']}", json=agent)

    assert response.status_code == 200
    record = response.json()
    assert record["config"] == agent
    assert record["id"] == created["id"]
    assert record["created_at"] == created["created_at"]
    assert record["updated_at"] >= created["updated_at"]
    assert client.get(f"/api/agents/{created['id']}").json() == record


def test_update_unknown_id_is_404(client, agent):
    response = client.put("/api/agents/nope", json=agent)

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_broken_graph_is_422_naming_the_edge(client, agent):
    agent["nodes"][1]["edges"][0]["target"] = "x"

    response = client.post("/api/agents", json=agent)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Edge 'record_details' in node 'collect_details' targets unknown node 'x'."
    }


def test_missing_initial_node_is_422(client, agent):
    del agent["initial_node"]

    response = client.post("/api/agents", json=agent)

    assert response.status_code == 422
    assert response.json() == {"detail": "Missing required field 'initial_node' in the agent."}


def test_missing_required_field_inside_the_graph_is_422(client, agent):
    del agent["nodes"][0]["edges"][0]["target"]

    response = client.post("/api/agents", json=agent)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Missing required field 'target' in edge 'choose_intent' of node 'greeting'."
    }


def test_rejected_create_stores_nothing(client, agent):
    agent["nodes"] = []

    assert client.post("/api/agents", json=agent).status_code == 422
    assert len(client.get("/api/agents").json()) == 1


def test_rejected_update_leaves_the_stored_agent_unchanged(client, agent):
    agent_id = _seeded_id(client)
    before = client.get(f"/api/agents/{agent_id}").json()
    agent["name"] = "Should not be saved"
    agent["nodes"][1]["edges"][0]["target"] = "x"

    response = client.put(f"/api/agents/{agent_id}", json=agent)

    assert response.status_code == 422
    assert client.get(f"/api/agents/{agent_id}").json() == before


def test_a_database_from_before_layouts_keeps_its_agents(tmp_path, monkeypatch, agent):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE agents (id TEXT PRIMARY KEY, config TEXT NOT NULL,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO agents VALUES ('old', ?, '2026-01-01T00:00:00.000+00:00',"
        " '2026-01-01T00:00:00.000+00:00')",
        (json.dumps(agent),),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv(agent_store.DB_PATH_ENV, str(path))

    store.init_db()
    store.init_db()  # a second start finds the column and leaves it alone

    [record] = store.list_agents()
    assert (record["id"], record["config"], record["layout"]) == ("old", agent, {})
    saved = store.update_agent("old", agent, {"greeting": {"x": 5, "y": 6}})
    assert saved["layout"] == {"greeting": {"x": 5, "y": 6}}
