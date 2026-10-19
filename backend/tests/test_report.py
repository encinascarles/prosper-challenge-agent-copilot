#
# Issues a person reports, through the API: a complaint from the clinic opened
# by hand, numbered like everything else, with the calls that show it. The
# model is scripted and the calls run on fakes: nothing here reaches OpenAI.
#

import copy

import pytest

from copilot import audit
from tests.conftest import settle
from tests.test_live import CALLERS, REVIEW

COMPLAINT = {
    "title": "Patient booked on a Sunday",
    "description": "From the clinic: a patient said Anna booked her on a Sunday, we are closed.",
    "reported": "clinic",
}


@pytest.fixture(autouse=True)
def two_callers(monkeypatch):
    monkeypatch.setattr(audit, "CALLERS_PER_BATCH", (2, 2))


def _report(client, agent_id, status=201, **more) -> dict:
    response = client.post(f"/api/agents/{agent_id}/issues", json={**COMPLAINT, **more})
    assert response.status_code == status, response.text
    return response.json()


def _calls(client, agent_id, prosper_model) -> list[dict]:
    """Play a batch of two calls that find nothing wrong: calls to link."""
    clean = {"outcome": "booked", "checks": REVIEW["checks"][:2], "findings": []}
    prosper_model.script = {"callers": [CALLERS], "audit": [clean, copy.deepcopy(clean)]}
    client.post(f"/api/agents/{agent_id}/calls/play")
    settle()
    return client.get(f"/api/agents/{agent_id}/calls").json()["calls"]


def test_a_reported_issue_is_numbered_with_pull_requests(client, live_agent):
    agent_id = live_agent()

    issue = _report(client, agent_id)  # PR #1 took number 1
    assert issue["number"] == 2
    assert (issue["state"], issue["reported"], issue["step"], issue["severity"]) == (
        "open",
        "clinic",
        "",
        None,
    )
    assert (issue["calls"], issue["findings"]) == (0, [])
    [event] = issue["events"]
    assert (event["type"], event["by"], event["text"]) == ("reported", "you", "clinic")

    pull = client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Tweak"}).json()
    assert pull["number"] == 3
    later = _report(client, agent_id, reported="you", step="offer_times", severity="booking")
    assert (later["number"], later["reported"], later["step"]) == (4, "you", "offer_times")
    listed = client.get(f"/api/agents/{agent_id}/issues").json()
    assert [i["number"] for i in listed] == [4, 2]


def test_a_report_names_a_real_step_and_real_calls_on_a_live_agent(client, live_agent, new_agent):
    agent_id = live_agent()
    assert "no step" in _report(client, agent_id, 409, step="nowhere")["detail"]
    assert "no call 99" in _report(client, agent_id, 404, calls=[99])["detail"]
    draft, _ = new_agent("Draft")
    assert "not live" in _report(client, draft, 409)["detail"]
    # Nothing half done: the refused reports took no number.
    assert _report(client, agent_id)["number"] == 2


def test_calls_linked_to_a_report_count_as_its_calls(client, live_agent, prosper_model):
    agent_id = live_agent()
    calls = _calls(client, agent_id, prosper_model)

    issue = _report(client, agent_id, calls=[calls[0]["id"]])
    assert issue["calls"] == 1
    [found] = issue["findings"]
    assert (found["call"], found["turn"], found["lines"]) == (calls[0]["id"], -1, [])

    listed = client.get(f"/api/agents/{agent_id}/calls").json()["calls"]
    assert {c["id"]: c["issues"] for c in listed}[calls[0]["id"]] == [issue["number"]]


def test_an_issue_found_in_calls_is_not_edited(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {"callers": [CALLERS], "audit": [copy.deepcopy(REVIEW)] * 2}
    prosper_model.script["grouping"] = [{"placements": [{"finding": 0, "issue": 2}]}]
    client.post(f"/api/agents/{agent_id}/calls/play")
    settle()
    path = f"/api/agents/{agent_id}/issues/2"
    assert client.patch(path, json={"title": "Mine"}).status_code == 409
