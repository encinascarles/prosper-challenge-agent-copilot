#
# Versions and pull requests end to end: HTTP in, SQLite on a temp file, HTTP out.
#
# The promise they pin: nothing reaches callers except by merging a pull
# request. Saving only ever writes a pull request's copy; merging validates it,
# adds the next version and makes it live; and a pull request copied from an
# older live version cannot merge over a newer one.
#

import json
import sqlite3

import pytest

import store


def _pulls(agent_id: str) -> str:
    return f"/api/agents/{agent_id}/pulls"


def _renamed(agent: dict, name: str) -> dict:
    return {**agent, "name": name}


# ---- before the agent is live --------------------------------------------------


def test_saving_pull_request_1_changes_its_copy_and_logs_it(client, new_agent, agent):
    agent_id, created = new_agent()
    agent["nodes"][0]["task_messages"][0]["content"] = "Say hello."

    response = client.put(f"{_pulls(agent_id)}/1", json={"config": agent})

    assert response.status_code == 200
    pull = response.json()
    assert pull["config"] == agent
    assert [e["type"] for e in pull["events"]] == ["opened", "saved"]
    assert pull["updated_at"] >= created["updated_at"]
    assert client.get(f"{_pulls(agent_id)}/1").json() == pull


def test_before_it_is_live_the_agent_is_named_after_pull_request_1(client, new_agent, agent):
    agent_id, _ = new_agent("Dental Recall")

    client.put(f"{_pulls(agent_id)}/1", json={"config": _renamed(agent, "Dental Recalls")})

    assert client.get(f"/api/agents/{agent_id}").json()["name"] == "Dental Recalls"


def test_an_agent_that_is_not_live_takes_changes_only_on_pull_request_1(client, new_agent):
    agent_id, _ = new_agent()

    response = client.post(_pulls(agent_id), json={"title": "Your edits"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": "The agent is not live yet: make changes on PR #1, then merge it."
    }


def test_pull_request_1_of_an_agent_that_is_not_live_cannot_be_closed(client, new_agent):
    agent_id, _ = new_agent()

    response = client.post(f"{_pulls(agent_id)}/1/close")

    assert response.status_code == 409
    assert "Delete the agent instead." in response.json()["detail"]
    assert client.get(f"{_pulls(agent_id)}/1").json()["state"] == "open"


# ---- merging ----------------------------------------------------------------


def test_merging_pull_request_1_puts_the_agent_live_as_v1(client, new_agent, agent):
    layout = {"greeting": {"x": 1, "y": 2}}
    agent_id, _ = new_agent(layout=layout)

    response = client.post(f"{_pulls(agent_id)}/1/merge")

    assert response.status_code == 200
    pull = response.json()
    assert (pull["state"], pull["merged_version"]) == ("merged", 1)
    assert [(e["type"], e.get("version")) for e in pull["events"]] == [
        ("opened", None),
        ("merged", 1),
    ]
    record = client.get(f"/api/agents/{agent_id}").json()
    assert (record["live_version"], record["open_pulls"]) == (1, 0)
    version = client.get(f"/api/agents/{agent_id}/versions/1").json()
    assert (version["config"], version["layout"], version["pull"]) == (
        _renamed(agent, "Dental Recall"),
        layout,
        1,
    )
    assert client.get(f"/api/agents/{agent_id}/versions").json() == [
        {"number": 1, "pull": 1, "title": "Set up Dental Recall", "created_at": pull["updated_at"]}
    ]


def test_a_pull_request_is_a_copy_of_live_numbered_from_the_agents_counter(
    client, live_agent, agent
):
    agent_id = live_agent()

    response = client.post(_pulls(agent_id), json={"title": "Your edits"})

    assert response.status_code == 201
    pull = response.json()
    assert (pull["number"], pull["title"], pull["kind"], pull["state"]) == (
        2,
        "Your edits",
        "edit",
        "open",
    )
    assert pull["base_version"] == 1
    assert pull["events"][0]["version"] == 1
    v1 = client.get(f"/api/agents/{agent_id}/versions/1").json()
    assert (pull["config"], pull["layout"]) == (v1["config"], v1["layout"])
    assert client.get(f"/api/agents/{agent_id}").json()["open_pulls"] == 1


def test_saving_a_pull_request_leaves_live_as_it_was(client, live_agent, agent):
    agent_id = live_agent()
    before = client.get(f"/api/agents/{agent_id}/versions/1").json()
    client.post(_pulls(agent_id), json={"title": "Your edits"})

    client.put(f"{_pulls(agent_id)}/2", json={"config": _renamed(agent, "Renamed")})

    assert client.get(f"/api/agents/{agent_id}/versions/1").json() == before
    record = client.get(f"/api/agents/{agent_id}").json()
    # The name lists show is live's until the rename is merged.
    assert (record["live_version"], record["name"]) == (1, "Dental Recall")


def test_merging_a_pull_request_adds_the_next_version_and_makes_it_live(
    client, live_agent, agent
):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})
    client.put(f"{_pulls(agent_id)}/2", json={"config": _renamed(agent, "Renamed")})

    response = client.post(f"{_pulls(agent_id)}/2/merge")

    assert response.status_code == 200
    assert response.json()["merged_version"] == 2
    record = client.get(f"/api/agents/{agent_id}").json()
    assert (record["live_version"], record["name"]) == (2, "Renamed")
    assert client.get(f"/api/agents/{agent_id}/versions/2").json()["config"]["name"] == "Renamed"
    # v1 is still there, as it was.
    assert client.get(f"/api/agents/{agent_id}/versions/1").json()["config"]["name"] == (
        "Dental Recall"
    )
    assert [v["number"] for v in client.get(f"/api/agents/{agent_id}/versions").json()] == [2, 1]


def test_a_pull_request_based_on_an_older_live_version_cannot_merge(client, live_agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "First"})
    client.post(_pulls(agent_id), json={"title": "Second"})
    assert client.post(f"{_pulls(agent_id)}/2/merge").status_code == 200

    response = client.post(f"{_pulls(agent_id)}/3/merge")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "PR #3 is based on v1, but live is now v2. "
        "It has to be updated to v2 before it can merge."
    }
    assert client.get(f"{_pulls(agent_id)}/3").json()["state"] == "open"
    assert client.get(f"/api/agents/{agent_id}").json()["live_version"] == 2


def test_an_invalid_copy_is_refused_at_merge_naming_where(client, live_agent, agent):
    # A copy passed the checks when it was saved; one that no longer does (a
    # rule added since) must not go live.
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})
    agent["nodes"][1]["edges"][0]["target"] = "x"
    with sqlite3.connect(store.db.db_path()) as conn:
        conn.execute(
            "UPDATE pulls SET config = ? WHERE agent_id = ? AND number = 2",
            (json.dumps(agent), agent_id),
        )

    response = client.post(f"{_pulls(agent_id)}/2/merge")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Edge 'record_details' in node 'collect_details' targets unknown node 'x'.",
        "node": "collect_details",
        "edge": "record_details",
    }
    assert client.get(f"/api/agents/{agent_id}").json()["live_version"] == 1


@pytest.mark.parametrize("ended", ["merge", "close"])
def test_a_pull_request_that_is_not_open_cannot_change(client, live_agent, agent, ended):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})
    client.post(f"{_pulls(agent_id)}/2/{ended}")
    state = {"merge": "merged", "close": "closed"}[ended]

    for response in (
        client.put(f"{_pulls(agent_id)}/2", json={"config": agent}),
        client.post(f"{_pulls(agent_id)}/2/merge"),
        client.post(f"{_pulls(agent_id)}/2/close"),
    ):
        assert response.status_code == 409
        assert response.json() == {"detail": f"PR #2 is {state}."}


def test_closing_a_pull_request_keeps_live_and_logs_it(client, live_agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})

    response = client.post(f"{_pulls(agent_id)}/2/close")

    assert response.status_code == 200
    pull = response.json()
    assert (pull["state"], pull["merged_version"]) == ("closed", None)
    assert [e["type"] for e in pull["events"]] == ["opened", "closed"]
    record = client.get(f"/api/agents/{agent_id}").json()
    assert (record["live_version"], record["open_pulls"]) == (1, 0)


def test_pull_requests_are_listed_newest_first_and_filtered_by_state(client, live_agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Closed one"})
    client.post(_pulls(agent_id), json={"title": "Open one"})
    client.post(f"{_pulls(agent_id)}/2/close")

    every = client.get(_pulls(agent_id)).json()
    open_ = client.get(_pulls(agent_id), params={"state": "open"}).json()

    assert [(p["number"], p["state"]) for p in every] == [(3, "open"), (2, "closed"), (1, "merged")]
    assert "config" not in every[0]  # the list carries no copies
    assert [p["number"] for p in open_] == [3]


def test_a_save_logs_what_it_changed_when_told(client, live_agent, agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})

    body = {"config": _renamed(agent, "Renamed"), "summary": "Changed the agent's settings"}
    pull = client.put(f"{_pulls(agent_id)}/2", json=body).json()

    assert pull["events"][-1]["type"] == "saved"
    assert pull["events"][-1]["summary"] == "Changed the agent's settings"


# ---- closing, reopening, renaming ------------------------------------------------


def test_a_closed_pull_request_reopens_as_it_was(client, live_agent, agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})
    saved = client.put(f"{_pulls(agent_id)}/2", json={"config": _renamed(agent, "Renamed")}).json()
    client.post(f"{_pulls(agent_id)}/2/close")

    response = client.post(f"{_pulls(agent_id)}/2/reopen")

    assert response.status_code == 200
    pull = response.json()
    assert (pull["state"], pull["config"], pull["base_version"]) == ("open", saved["config"], 1)
    assert [e["type"] for e in pull["events"]] == ["opened", "saved", "closed", "reopened"]
    assert client.get(f"/api/agents/{agent_id}").json()["open_pulls"] == 1


@pytest.mark.parametrize("state", ["open", "merged"])
def test_only_a_closed_pull_request_can_be_reopened(client, live_agent, state):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})
    if state == "merged":
        client.post(f"{_pulls(agent_id)}/2/merge")

    response = client.post(f"{_pulls(agent_id)}/2/reopen")

    assert (response.status_code, response.json()) == (409, {"detail": f"PR #2 is {state}."})


def test_an_open_pull_request_can_be_renamed(client, live_agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})

    response = client.patch(f"{_pulls(agent_id)}/2", json={"title": "  Shorter greeting "})

    assert response.status_code == 200
    assert response.json()["title"] == "Shorter greeting"
    assert [e["type"] for e in response.json()["events"]] == ["opened"]
    assert client.patch(f"{_pulls(agent_id)}/2", json={"title": "  "}).status_code == 422


# ---- updating a pull request left behind ------------------------------------------


@pytest.fixture
def left_behind(client, live_agent, agent):
    """An agent live as v2 from PR #2, and PR #3 still based on v1. Returns its id."""

    def create() -> str:
        agent_id = live_agent()
        client.post(_pulls(agent_id), json={"title": "First"})
        client.post(_pulls(agent_id), json={"title": "Second"})
        client.put(f"{_pulls(agent_id)}/2", json={"config": _renamed(agent, "Renamed")})
        assert client.post(f"{_pulls(agent_id)}/2/merge").status_code == 200
        return agent_id

    return create


def test_updating_bases_the_pull_request_on_live_and_lets_it_merge(client, left_behind, agent):
    agent_id = left_behind()
    replayed = _renamed(agent, "Renamed again")
    body = {
        "config": replayed,
        "layout": {"greeting": {"x": 5, "y": 6}, "ghost": {"x": 0, "y": 0}},
        "onto": 2,
        "summary": "kept your text in Greeting",
    }

    response = client.post(f"{_pulls(agent_id)}/3/update", json=body)

    assert response.status_code == 200
    pull = response.json()
    assert (pull["base_version"], pull["config"]) == (2, replayed)
    assert pull["layout"] == {"greeting": {"x": 5, "y": 6}}
    event = pull["events"][-1]
    assert (event["type"], event["version"], event["summary"]) == (
        "updated",
        2,
        "kept your text in Greeting",
    )
    assert client.post(f"{_pulls(agent_id)}/3/merge").json()["merged_version"] == 3


def test_an_update_replayed_on_a_version_that_is_no_longer_live_is_refused(
    client, left_behind, agent
):
    agent_id = left_behind()

    response = client.post(f"{_pulls(agent_id)}/3/update", json={"config": agent, "onto": 1})

    assert (response.status_code, response.json()) == (
        409,
        {"detail": "Live is v2 now, not v1. Update it again."},
    )
    assert client.get(f"{_pulls(agent_id)}/3").json()["base_version"] == 1


def test_a_pull_request_on_live_has_nothing_to_update(client, live_agent, agent):
    agent_id = live_agent()
    client.post(_pulls(agent_id), json={"title": "Your edits"})

    response = client.post(f"{_pulls(agent_id)}/2/update", json={"config": agent, "onto": 1})

    assert (response.status_code, response.json()) == (
        409,
        {"detail": "PR #2 is already based on v1."},
    )


def test_an_update_that_is_not_an_agent_is_422_and_changes_nothing(client, left_behind, agent):
    agent_id = left_behind()
    before = client.get(f"{_pulls(agent_id)}/3").json()
    agent["nodes"][0]["edges"][0]["target"] = "gone"

    response = client.post(f"{_pulls(agent_id)}/3/update", json={"config": agent, "onto": 2})

    assert response.status_code == 422
    assert response.json()["node"] == "greeting"
    assert client.get(f"{_pulls(agent_id)}/3").json() == before


# ---- what the API refuses -------------------------------------------------------


def test_live_cannot_be_edited_through_the_api(client, live_agent, agent):
    agent_id = live_agent()

    assert client.put(f"/api/agents/{agent_id}", json={"config": agent}).status_code == 405
    for method in ("put", "patch", "delete"):
        response = getattr(client, method)(f"/api/agents/{agent_id}/versions/1")
        assert response.status_code == 405
    assert client.post(f"/api/agents/{agent_id}/versions", json={}).status_code == 405


def test_a_rejected_save_names_where_and_changes_nothing(client, new_agent, agent):
    agent_id, before = new_agent()
    agent["nodes"][0]["edges"][0]["target"] = ""
    moved = {"greeting": {"x": 999, "y": 999}}

    response = client.put(f"{_pulls(agent_id)}/1", json={"config": agent, "layout": moved})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Edge 'choose_intent' in node 'greeting' targets unknown node ''.",
        "node": "greeting",
        "edge": "choose_intent",
    }
    assert client.get(f"{_pulls(agent_id)}/1").json() == before


def test_a_position_without_coordinates_is_422_and_saves_nothing(client, new_agent, agent):
    agent_id, before = new_agent()

    response = client.put(
        f"{_pulls(agent_id)}/1",
        json={"config": _renamed(agent, "Nope"), "layout": {"greeting": {"x": 1}}},
    )

    assert response.status_code == 422
    assert client.get(f"{_pulls(agent_id)}/1").json() == before


@pytest.mark.parametrize(
    "path, detail",
    [
        ("/api/agents/nope/pulls", "No agent with id 'nope'."),
        ("/api/agents/nope/versions", "No agent with id 'nope'."),
        ("/api/agents/{id}/pulls/9", "The agent has no PR #9."),
        ("/api/agents/{id}/versions/9", "The agent has no v9."),
    ],
)
def test_what_does_not_exist_is_404(client, live_agent, path, detail):
    response = client.get(path.format(id=live_agent()))

    assert (response.status_code, response.json()) == (404, {"detail": detail})


@pytest.mark.parametrize("action", ["merge", "close", "reopen"])
def test_changing_a_pull_request_that_does_not_exist_is_404(client, live_agent, action):
    agent_id = live_agent()

    response = client.post(f"{_pulls(agent_id)}/9/{action}")

    assert (response.status_code, response.json()) == (404, {"detail": "The agent has no PR #9."})


def test_opening_on_an_unknown_agent_is_404(client):
    response = client.post(_pulls("nope"), json={"title": "Your edits"})

    assert (response.status_code, response.json()) == (404, {"detail": "No agent with id 'nope'."})


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "Fix", "kind": "setup"}], ids=str)
def test_a_pull_request_needs_a_title_and_is_an_edit(client, live_agent, body):
    assert client.post(_pulls(live_agent()), json=body).status_code == 422


# ---- layouts on a copy ------------------------------------------------------------


def test_a_save_keeps_the_layout_pruned_to_the_agents_nodes(client, new_agent, agent):
    agent_id, _ = new_agent()
    layout = {"greeting": {"x": 40, "y": -12.5}, "ghost": {"x": 3, "y": 4}}

    response = client.put(f"{_pulls(agent_id)}/1", json={"config": agent, "layout": layout})

    assert response.json()["layout"] == {"greeting": {"x": 40, "y": -12.5}}
    assert response.json()["config"] == agent  # positions never leak into the agent JSON


def test_a_save_without_a_layout_keeps_the_stored_one_minus_removed_nodes(
    client, new_agent, agent
):
    end = agent["nodes"][-1]["name"]
    agent_id, _ = new_agent(layout={"greeting": {"x": 1, "y": 2}, end: {"x": 3, "y": 4}})
    agent["nodes"] = agent["nodes"][-1:]  # the terminal node alone is a valid graph
    agent["initial_node"] = end

    response = client.put(f"{_pulls(agent_id)}/1", json={"config": agent})

    assert response.json()["layout"] == {end: {"x": 3, "y": 4}}


def test_an_empty_layout_clears_the_stored_one(client, new_agent, agent):
    agent_id, _ = new_agent(layout={"greeting": {"x": 1, "y": 2}})

    response = client.put(f"{_pulls(agent_id)}/1", json={"config": agent, "layout": {}})

    assert response.json()["layout"] == {}
