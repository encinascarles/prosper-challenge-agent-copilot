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


def test_init_db_seeds_only_a_new_database(client):
    store.init_db()  # what a server restart does

    assert len(client.get("/api/agents").json()) == 1


def test_the_seed_does_not_come_back_once_every_agent_is_deleted(client):
    assert client.delete(f"/api/agents/{_seeded_id(client)}").status_code == 204

    store.init_db()  # the next start

    assert client.get("/api/agents").json() == []


def test_a_broken_seed_is_refused_and_a_fixed_one_still_seeds(tmp_path, monkeypatch, agent):
    good = agent_store.SEED_FLOW
    broken_agent = json.loads(json.dumps(agent))
    broken_agent["nodes"][0]["edges"][0]["target"] = "x"
    broken = tmp_path / "broken_flow.json"
    broken.write_text(json.dumps(broken_agent))
    monkeypatch.setenv(agent_store.DB_PATH_ENV, str(tmp_path / "empty.db"))
    monkeypatch.setattr(agent_store, "SEED_FLOW", broken)

    with pytest.raises(ValueError, match="targets unknown node 'x'"):
        store.init_db()

    # Nothing was created, so the start after the sample is fixed seeds it.
    monkeypatch.setattr(agent_store, "SEED_FLOW", good)
    store.init_db()
    assert [record["config"]["name"] for record in store.list_agents()] == [agent["name"]]


def test_get_returns_the_full_agent(client, agent):
    response = client.get(f"/api/agents/{_seeded_id(client)}")

    assert response.status_code == 200
    record = response.json()
    assert set(record) == {"id", "config", "layout", "created_at", "updated_at"}
    assert record["config"] == agent
    assert record["layout"] == {}  # nothing placed yet: the editor lays it out


def test_get_unknown_id_is_404(client):
    response = client.get("/api/agents/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_create_stores_the_agent_and_returns_its_record(client, agent):
    agent["name"] = "Dental Recall"

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 201
    record = response.json()
    assert record["config"] == agent
    assert record["layout"] == {}
    assert record["created_at"] == record["updated_at"]
    assert client.get(f"/api/agents/{record['id']}").json() == record
    assert [a["name"] for a in client.get("/api/agents").json()] == [
        "Prosper Scheduler",
        "Dental Recall",
    ]


def test_create_saves_the_layout_pruned_to_the_agents_nodes(client, agent):
    layout = {"greeting": {"x": 1, "y": 2}, "ghost": {"x": 3, "y": 4}}

    response = client.post("/api/agents", json={"config": agent, "layout": layout})

    assert response.status_code == 201
    record = response.json()
    assert record["layout"] == {"greeting": {"x": 1, "y": 2}}
    assert client.get(f"/api/agents/{record['id']}").json() == record


def test_update_replaces_the_agent(client, agent):
    created = client.post("/api/agents", json={"config": agent}).json()
    agent["name"] = "Renamed"
    agent["nodes"] = agent["nodes"][-1:]  # the terminal node alone is a valid graph
    agent["initial_node"] = agent["nodes"][0]["name"]

    response = client.put(f"/api/agents/{created['id']}", json={"config": agent})

    assert response.status_code == 200
    record = response.json()
    assert record["config"] == agent
    assert record["id"] == created["id"]
    assert record["created_at"] == created["created_at"]
    assert record["updated_at"] >= created["updated_at"]
    assert client.get(f"/api/agents/{created['id']}").json() == record


def test_update_unknown_id_is_404(client, agent):
    response = client.put("/api/agents/nope", json={"config": agent})

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_broken_graph_is_422_naming_the_edge(client, agent):
    agent["nodes"][1]["edges"][0]["target"] = "x"

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Edge 'record_details' in node 'collect_details' targets unknown node 'x'.",
        "node": "collect_details",
        "edge": "record_details",
    }


def test_missing_initial_node_is_422(client, agent):
    del agent["initial_node"]

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 422
    assert response.json() == {"detail": "Missing required field 'initial_node' in the agent."}


def test_missing_required_field_inside_the_graph_is_422(client, agent):
    del agent["nodes"][0]["edges"][0]["target"]

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Missing required field 'target' in edge 'choose_intent' of node 'greeting'.",
        "node": "greeting",
        "edge": "choose_intent",
    }


def test_problem_in_a_node_names_the_node_and_no_edge(client, agent):
    agent["nodes"][2]["task_messages"] = "Offer two times."

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "'task_messages' in node 'offer_times' must be a list, got a string.",
        "node": "offer_times",
    }


def test_duplicate_node_names_the_node(client, agent):
    agent["nodes"][3]["name"] = "greeting"

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 422
    assert response.json()["node"] == "greeting"
    assert "edge" not in response.json()


def test_rejected_update_names_the_node_and_edge(client, agent):
    created = client.post("/api/agents", json={"config": agent}).json()
    agent["nodes"][0]["edges"][0]["target"] = ""

    response = client.put(f"/api/agents/{created['id']}", json={"config": agent})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Edge 'choose_intent' in node 'greeting' targets unknown node ''.",
        "node": "greeting",
        "edge": "choose_intent",
    }
    # And the stored agent is still the valid one.
    stored = client.get(f"/api/agents/{created['id']}").json()
    assert stored["config"]["nodes"][0]["edges"][0]["target"] == "collect_details"


def test_rejected_create_stores_nothing(client, agent):
    agent["nodes"] = []

    assert client.post("/api/agents", json={"config": agent}).status_code == 422
    assert len(client.get("/api/agents").json()) == 1


def test_rejected_update_leaves_the_stored_agent_unchanged(client, agent):
    agent_id = _seeded_id(client)
    before = client.get(f"/api/agents/{agent_id}").json()
    agent["name"] = "Should not be saved"
    agent["nodes"][1]["edges"][0]["target"] = "x"

    moved = {"greeting": {"x": 999, "y": 999}}
    response = client.put(f"/api/agents/{agent_id}", json={"config": agent, "layout": moved})

    assert response.status_code == 422
    assert client.get(f"/api/agents/{agent_id}").json() == before


def test_layout_is_saved_with_the_agent_and_read_back(client, agent):
    agent_id = _seeded_id(client)
    layout = {"greeting": {"x": 40, "y": -12.5}, "collect_details": {"x": 380, "y": 0}}

    response = client.put(f"/api/agents/{agent_id}", json={"config": agent, "layout": layout})

    assert response.status_code == 200
    assert response.json()["layout"] == layout
    record = client.get(f"/api/agents/{agent_id}").json()
    assert record["layout"] == layout
    assert record["config"] == agent  # positions never leak into the agent JSON


def test_layout_drops_positions_of_names_that_are_not_nodes(client, agent):
    agent_id = _seeded_id(client)
    layout = {"greeting": {"x": 1, "y": 2}, "ghost": {"x": 3, "y": 4}}

    response = client.put(f"/api/agents/{agent_id}", json={"config": agent, "layout": layout})

    assert response.json()["layout"] == {"greeting": {"x": 1, "y": 2}}
    assert client.get(f"/api/agents/{agent_id}").json()["layout"] == {"greeting": {"x": 1, "y": 2}}


def test_update_without_a_layout_keeps_the_stored_one(client, agent):
    agent_id = _seeded_id(client)
    layout = {"greeting": {"x": 1, "y": 2}}
    client.put(f"/api/agents/{agent_id}", json={"config": agent, "layout": layout})
    agent["name"] = "Renamed"

    response = client.put(f"/api/agents/{agent_id}", json={"config": agent})

    assert response.json()["config"]["name"] == "Renamed"
    assert response.json()["layout"] == layout


def test_update_without_a_layout_still_drops_removed_nodes(client, agent):
    agent_id = _seeded_id(client)
    end = agent["nodes"][-1]["name"]
    layout = {"greeting": {"x": 1, "y": 2}, end: {"x": 3, "y": 4}}
    client.put(f"/api/agents/{agent_id}", json={"config": agent, "layout": layout})
    agent["nodes"] = agent["nodes"][-1:]
    agent["initial_node"] = end

    response = client.put(f"/api/agents/{agent_id}", json={"config": agent})

    assert response.json()["layout"] == {end: {"x": 3, "y": 4}}


def test_an_empty_layout_clears_the_stored_one(client, agent):
    agent_id = _seeded_id(client)
    client.put(
        f"/api/agents/{agent_id}", json={"config": agent, "layout": {"greeting": {"x": 1, "y": 2}}}
    )

    response = client.put(f"/api/agents/{agent_id}", json={"config": agent, "layout": {}})

    assert response.json()["layout"] == {}


def test_a_position_without_coordinates_is_422_and_saves_nothing(client, agent):
    agent_id = _seeded_id(client)
    before = client.get(f"/api/agents/{agent_id}").json()
    agent["name"] = "Should not be saved"

    response = client.put(
        f"/api/agents/{agent_id}", json={"config": agent, "layout": {"greeting": {"x": 1}}}
    )

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


def test_delete_removes_the_agent_and_only_that_one(client, agent):
    kept = client.post("/api/agents", json={"config": agent}).json()
    gone = client.post("/api/agents", json={"config": {**agent, "name": "To delete"}}).json()

    response = client.delete(f"/api/agents/{gone['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/agents/{gone['id']}").status_code == 404
    listed = [row["id"] for row in client.get("/api/agents").json()]
    assert gone["id"] not in listed
    assert kept["id"] in listed


def test_delete_unknown_agent_is_404(client):
    response = client.delete("/api/agents/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_deleting_twice_is_404_the_second_time(client, agent):
    created = client.post("/api/agents", json={"config": agent}).json()

    assert client.delete(f"/api/agents/{created['id']}").status_code == 204
    assert client.delete(f"/api/agents/{created['id']}").status_code == 404
