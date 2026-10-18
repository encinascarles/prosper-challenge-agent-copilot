#
# The agents API end to end: HTTP in, SQLite on a temp file, HTTP out.
#
# These go through the real router, AgentBuilder and store, so they cover the
# promise the editor relies on: whatever the API stored is an agent that runs,
# a new agent waits on its pull request #1, and a rejected request changes
# nothing. Saving and merging are in test_pulls_api.py.
#

import json
import sqlite3

import pytest

import store
from store import agents as agent_store
from store.db import DB_PATH_ENV


def _seeded_id(client) -> str:
    return client.get("/api/agents").json()[0]["id"]


def test_list_starts_with_the_seeded_example_live_as_v1(client, agent):
    response = client.get("/api/agents")

    assert response.status_code == 200
    [summary] = response.json()
    assert set(summary) == {"id", "name", "live_version", "open_pulls", "created_at", "updated_at"}
    assert (summary["name"], summary["live_version"], summary["open_pulls"]) == (
        agent["name"],
        1,
        0,
    )


def test_the_seeded_v1_is_the_example_and_comes_from_no_pull_request(client, agent):
    agent_id = _seeded_id(client)

    version = client.get(f"/api/agents/{agent_id}/versions/1").json()

    assert (version["config"], version["layout"], version["pull"]) == (agent, {}, None)
    assert client.get(f"/api/agents/{agent_id}/pulls").json() == []


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
    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path / "empty.db"))
    monkeypatch.setattr(agent_store, "SEED_FLOW", broken)

    with pytest.raises(ValueError, match="targets unknown node 'x'"):
        store.init_db()

    # Nothing was created, so the start after the sample is fixed seeds it.
    monkeypatch.setattr(agent_store, "SEED_FLOW", good)
    store.init_db()
    assert [record["name"] for record in store.list_agents()] == [agent["name"]]


def test_get_returns_the_agent(client, agent):
    agent_id = _seeded_id(client)

    response = client.get(f"/api/agents/{agent_id}")

    assert response.status_code == 200
    assert response.json() == client.get("/api/agents").json()[0]


def test_get_unknown_id_is_404(client):
    response = client.get("/api/agents/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_a_new_agent_is_not_live_and_has_its_pull_request_1(client, agent):
    agent["name"] = "Dental Recall"

    response = client.post("/api/agents", json={"config": agent})

    assert response.status_code == 201
    created = response.json()
    new, pull = created["agent"], created["pull"]
    assert (new["name"], new["live_version"], new["open_pulls"]) == ("Dental Recall", 0, 1)
    assert client.get(f"/api/agents/{new['id']}").json() == new
    assert (pull["number"], pull["title"], pull["kind"], pull["state"]) == (
        1,
        "Set up Dental Recall",
        "setup",
        "open",
    )
    assert (pull["base_version"], pull["merged_version"]) == (0, None)
    assert (pull["config"], pull["layout"]) == (agent, {})
    assert [(e["type"], e["by"]) for e in pull["events"]] == [("opened", "you")]
    assert client.get(f"/api/agents/{new['id']}/versions").json() == []
    assert [a["name"] for a in client.get("/api/agents").json()] == [
        "Prosper Scheduler",
        "Dental Recall",
    ]


def test_create_saves_the_layout_on_pull_request_1_pruned_to_the_agents_nodes(client, agent):
    layout = {"greeting": {"x": 1, "y": 2}, "ghost": {"x": 3, "y": 4}}

    response = client.post("/api/agents", json={"config": agent, "layout": layout})

    assert response.json()["pull"]["layout"] == {"greeting": {"x": 1, "y": 2}}


def test_an_agent_cannot_be_overwritten(client, agent):
    # Changes go through a pull request: there is no route that writes over an agent.
    response = client.put(f"/api/agents/{_seeded_id(client)}", json={"config": agent})

    assert response.status_code == 405


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


def test_rejected_create_stores_nothing(client, agent):
    agent["nodes"] = []

    assert client.post("/api/agents", json={"config": agent}).status_code == 422
    assert len(client.get("/api/agents").json()) == 1


def _old_database(path, agent, with_layout: bool) -> None:
    """A database as the store left it before versions: the graph in the agent's row."""
    conn = sqlite3.connect(path)
    layout_column = ", layout TEXT NOT NULL DEFAULT '{}'" if with_layout else ""
    conn.execute(
        "CREATE TABLE agents (id TEXT PRIMARY KEY, config TEXT NOT NULL"
        f"{layout_column}, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    columns = "id, config, created_at, updated_at" + (", layout" if with_layout else "")
    values = ["old", json.dumps(agent), "2026-01-01T00:00:00.000+00:00"]
    values.append("2026-01-02T00:00:00.000+00:00")
    if with_layout:
        values.append(json.dumps({"greeting": {"x": 5, "y": 6}}))
    conn.execute(f"INSERT INTO agents ({columns}) VALUES ({', '.join('?' * len(values))})", values)
    conn.commit()
    conn.close()


@pytest.mark.parametrize("with_layout", [True, False], ids=["with layouts", "before layouts"])
def test_a_database_from_before_versions_keeps_its_agents_as_v1(
    tmp_path, monkeypatch, agent, with_layout
):
    path = tmp_path / "old.db"
    _old_database(path, agent, with_layout)
    monkeypatch.setenv(DB_PATH_ENV, str(path))

    store.init_db()
    store.init_db()  # a second start finds it migrated and leaves it alone

    [record] = store.list_agents()
    assert (record["id"], record["name"], record["live_version"]) == ("old", agent["name"], 1)
    version = store.get_version("old", 1)
    assert (version["config"], version["pull"]) == (agent, None)
    assert version["layout"] == ({"greeting": {"x": 5, "y": 6}} if with_layout else {})
    assert version["created_at"] == "2026-01-02T00:00:00.000+00:00"  # when it was last saved
    assert store.list_pulls("old") == []
    # And it works like any agent: the next change is pull request #1.
    assert store.open_pull("old", "Your edits", "edit", by="you")["number"] == 1


def test_delete_removes_the_agent_its_versions_and_pull_requests(client, live_agent):
    kept = live_agent("Kept")
    gone = live_agent("To delete")
    client.post(f"/api/agents/{gone}/pulls", json={"title": "Your edits"})

    response = client.delete(f"/api/agents/{gone}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/agents/{gone}").status_code == 404
    assert client.get(f"/api/agents/{gone}/versions").status_code == 404
    listed = [row["id"] for row in client.get("/api/agents").json()]
    assert gone not in listed
    assert kept in listed
    with sqlite3.connect(store.db.db_path()) as conn:
        for table in ("versions", "pulls"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE agent_id = ?", (gone,))
            assert count.fetchone() == (0,)


def test_delete_unknown_agent_is_404(client):
    response = client.delete("/api/agents/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "No agent with id 'nope'."}


def test_deleting_twice_is_404_the_second_time(client, new_agent):
    agent_id, _ = new_agent()

    assert client.delete(f"/api/agents/{agent_id}").status_code == 204
    assert client.delete(f"/api/agents/{agent_id}").status_code == 404
