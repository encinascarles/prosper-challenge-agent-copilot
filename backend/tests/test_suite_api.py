#
# Rules, tests and checks through the API: added to a pull request's copy,
# taken out again only there, run on every change, and in the way of a merge
# until they pass. The simulated calls run on fakes (tests/fakes.py).
#

import pytest

import api
from api import checks


def _pull(agent_id: str, number: int = 2) -> str:
    return f"/api/agents/{agent_id}/pulls/{number}"


@pytest.fixture
def on_pull(client, live_agent):
    """A live agent with PR #2 open on it. Returns the agent's id."""
    agent_id = live_agent()
    client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Your edits"})
    return agent_id


def _add_test(client, agent_id: str, checks_: list[str], name: str = "Books") -> dict:
    body = {"name": name, "caller": "Maria wants a check-up.", "checks": checks_}
    response = client.post(f"{_pull(agent_id)}/tests", json=body)
    assert response.status_code == 200, response.json()
    checks.wait()
    return response.json()


def test_the_sample_agent_starts_live_with_a_suite(client):
    (sample,) = client.get("/api/agents").json()

    version = client.get(f"/api/agents/{sample['id']}/versions/1").json()

    assert version["rules"] == []
    assert [test["name"] for test in version["tests"]] == [
        "Books a check-up",
        "Reschedules an appointment",
        "Cancels an appointment",
        "Asks for medical advice",
        "Gives everything at once",
    ]
    assert all(test["source"] == {"kind": "manual", "pull": None} for test in version["tests"])


def test_a_rule_is_added_to_the_pull_request_and_logged(client, on_pull):
    response = client.post(
        f"{_pull(on_pull)}/rules", json={"step": "confirm", "text": " Read the date back. "}
    )

    assert response.status_code == 200
    pull = response.json()
    (rule,) = pull["rules"]
    assert (rule["step"], rule["text"], rule["source"]) == (
        "confirm",
        "Read the date back.",
        {"kind": "manual", "pull": 2},
    )
    event = pull["events"][-1]
    assert (event["type"], event["step"]) == ("rule", "confirm")
    assert event["text"] == "Read the date back."
    assert client.get(f"/api/agents/{on_pull}/versions/1").json()["rules"] == []


def test_a_rule_for_every_step_has_no_step_and_one_for_no_step_is_refused(client, on_pull):
    every = client.post(f"{_pull(on_pull)}/rules", json={"text": "Be brief."})
    nowhere = client.post(f"{_pull(on_pull)}/rules", json={"step": "x", "text": "Hi."})

    assert every.json()["rules"][0]["step"] is None
    assert (nowhere.status_code, nowhere.json()) == (
        409,
        {"detail": "There is no step 'x' in PR #2."},
    )


def test_a_rule_or_test_is_taken_out_only_in_the_pull_request_that_added_it(client, on_pull):
    rule = client.post(f"{_pull(on_pull)}/rules", json={"text": "Be brief."}).json()["rules"][0]
    live_test = client.get(_pull(on_pull)).json()["tests"]

    removed = client.delete(f"{_pull(on_pull)}/rules/{rule['id']}")

    assert removed.status_code == 200
    assert removed.json()["rules"] == []
    assert removed.json()["events"][-1]["removed"] is True
    # The agent made from the sample has no tests; the sample agent has, live.
    assert live_test == []
    (sample,) = [a for a in client.get("/api/agents").json() if a["id"] != on_pull]
    client.post(f"/api/agents/{sample['id']}/pulls", json={"title": "Edits"})
    test_id = client.get(_pull(sample["id"], 1)).json()["tests"][0]["id"]
    refused = client.delete(f"{_pull(sample['id'], 1)}/tests/{test_id}")
    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "That test was not added in PR #1."},
    )


def test_a_test_needs_a_name_a_caller_and_a_check(client, on_pull):
    body = {"name": "Books", "caller": "Maria.", "checks": ["  ", ""]}

    response = client.post(f"{_pull(on_pull)}/tests", json=body)

    assert response.status_code == 422


def test_adding_a_test_runs_the_suite_three_times_per_test(client, on_pull):
    _add_test(client, on_pull, ["Reaches Confirm", "Ends the call", "Is polite"])

    run = client.get(f"{_pull(on_pull)}/checks").json()

    assert run["state"] == "done"
    (test,) = run["tests"]
    assert len(test["runs"]) == 3
    first = test["runs"][0]
    assert first["passed"] is True
    assert [check["kind"] for check in first["checks"]] == ["reaches", "ends", "judged"]
    assert first["checks"][0]["pass"] is True
    assert [step["node"] for step in first["path"]][-1] == "confirm"
    assert first["path"][1]["from"] == "greeting"
    pull = client.get(_pull(on_pull)).json()
    assert pull["checks"] == {"state": "passed", "passed": 1, "failing": 0, "total": 1}
    event = pull["events"][-1]
    assert (event["type"], event["passed"], event["total"]) == ("checks", 1, 1)


def test_a_failing_test_blocks_the_merge(client, on_pull, fake_checks):
    fake_checks.verdict = False
    _add_test(client, on_pull, ["Reaches Confirm", "Never gives medical advice"])

    response = client.post(f"{_pull(on_pull)}/merge")

    assert (response.status_code, response.json()) == (
        409,
        {"detail": "PR #2 cannot merge: 1 test failing."},
    )
    checks_ = client.get(_pull(on_pull)).json()["checks"]
    assert checks_ == {"state": "failed", "passed": 0, "failing": 1, "total": 1}


def test_running_checks_block_the_merge(client, on_pull, monkeypatch):
    # A run that has started and not finished: nothing is calling it.
    monkeypatch.setattr(checks, "_run", _never_runs)
    _add_test(client, on_pull, ["Reaches Confirm"])

    response = client.post(f"{_pull(on_pull)}/merge")

    assert response.json() == {"detail": "PR #2 cannot merge: its checks are still running."}
    assert client.get(_pull(on_pull)).json()["checks"]["state"] == "running"


async def _never_runs(agent_id, run, copy):
    return None


def test_a_merge_puts_rules_and_tests_live_with_their_checks(client, on_pull):
    client.post(f"{_pull(on_pull)}/rules", json={"step": "confirm", "text": "Spell the name."})
    _add_test(client, on_pull, ["Reaches Confirm"])

    merged = client.post(f"{_pull(on_pull)}/merge")

    assert merged.status_code == 200
    version = client.get(f"/api/agents/{on_pull}/versions/2").json()
    assert [rule["text"] for rule in version["rules"]] == ["Spell the name."]
    assert [test["name"] for test in version["tests"]] == ["Books"]
    run = client.get(f"/api/agents/{on_pull}/versions/2/checks").json()
    assert (run["pull"], run["version"]) == (2, 2)


def test_a_version_runs_its_checks_by_hand(client):
    (sample,) = client.get("/api/agents").json()
    url = f"/api/agents/{sample['id']}/versions/1/checks"
    assert client.get(url).json() is None

    started = client.post(url)
    checks.wait()

    assert started.json()["state"] == "running"
    run = client.get(url).json()
    assert run["state"] == "done"
    assert [len(test["runs"]) for test in run["tests"]] == [3] * 5


def test_a_save_carries_rules_to_renamed_steps_and_drops_those_of_removed_ones(
    client, on_pull, agent
):
    client.post(f"{_pull(on_pull)}/rules", json={"step": "confirm", "text": "Spell the name."})
    client.post(f"{_pull(on_pull)}/rules", json={"step": "offer_times", "text": "Two slots."})
    agent["nodes"][3]["name"] = "wrap_up"
    agent["nodes"][2]["edges"][0]["target"] = "wrap_up"

    renamed = client.put(_pull(on_pull), json={"config": agent, "renames": {"confirm": "wrap_up"}})

    assert [(r["step"], r["text"]) for r in renamed.json()["rules"]] == [
        ("wrap_up", "Spell the name."),
        ("offer_times", "Two slots."),
    ]
    agent["nodes"][1]["edges"][0]["target"] = "wrap_up"
    del agent["nodes"][2]
    dropped = client.put(_pull(on_pull), json={"config": agent})
    assert [r["step"] for r in dropped.json()["rules"]] == ["wrap_up"]


def test_an_update_keeps_the_pull_requests_own_rules_on_top_of_live(client, on_pull):
    client.post(f"/api/agents/{on_pull}/pulls", json={"title": "Second"})
    client.post(f"{_pull(on_pull, 3)}/rules", json={"text": "From PR #3."})
    client.post(f"{_pull(on_pull)}/rules", json={"text": "From PR #2."})
    _add_test(client, on_pull, ["Reaches Confirm"])
    assert client.post(f"{_pull(on_pull)}/merge").status_code == 200
    stale = client.get(_pull(on_pull, 3)).json()

    updated = client.post(
        f"{_pull(on_pull, 3)}/update", json={"config": stale["config"], "onto": 2}
    )

    assert [rule["text"] for rule in updated.json()["rules"]] == ["From PR #2.", "From PR #3."]
    assert [test["name"] for test in updated.json()["tests"]] == ["Books"]


def test_a_call_on_a_pull_request_is_told_its_rules(client, on_pull):
    client.post(f"{_pull(on_pull)}/rules", json={"text": "Be brief."})

    builder = api.agent_for_call({"agent_id": on_pull, "pull": 2})

    assert [(rule["step"], rule["text"]) for rule in builder.rules] == [(None, "Be brief.")]
