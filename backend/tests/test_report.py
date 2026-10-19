#
# Issues a person reports, through the API: a complaint from the clinic opened
# by hand, numbered like everything else, with the calls that show it;
# tidied by Prosper AI when asked; fixed by Prosper AI from its description
# alone, and joined by a finding from calls like any other issue. The model is
# scripted and the calls run on fakes: nothing here reaches OpenAI.
#

import copy

import pytest

import store
from copilot import audit
from tests.conftest import settle
from tests.test_fix import FIX, TEST
from tests.test_live import CALLERS, REVIEW

COMPLAINT = {
    "title": "Patient booked on a Sunday",
    "description": "From the clinic: a patient said Anna booked her on a Sunday, we are closed.",
    "reported": "clinic",
}


@pytest.fixture(autouse=True)
def two_callers(monkeypatch):
    monkeypatch.setattr(audit, "CALLERS_PER_BATCH", (2, 2))


@pytest.fixture
def verdicts(fake_checks):
    """What the judge says, in order; past the list, every check passes."""
    said: list[bool] = []

    async def judge(check, transcript):
        verdict = said.pop(0) if said else True
        return {"pass": verdict, "detail": "Judged.", "tokens": {"prompt": 1, "completion": 1}}

    fake_checks.judge = judge
    return said


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


def test_a_reported_issue_is_edited_and_kept_tidied_by_prosper_ai(
    client, live_agent, prosper_model
):
    agent_id = live_agent()
    calls = _calls(client, agent_id, prosper_model)
    number = _report(client, agent_id)["number"]
    tidied = {
        "title": "Books appointments on Sundays",
        "step": "offer_times",
        "severity": "booking",
        "calls": [calls[1]["id"]],
    }
    # A step that does not exist is sent back, and the answer comes again.
    prosper_model.script = {"tidy": [{**tidied, "step": "sunday_slots"}, tidied]}

    response = client.post(f"/api/agents/{agent_id}/issues/{number}/tidy")
    assert response.status_code == 200, response.text
    assert {k: v for k, v in response.json().items() if k != "usd"} == tidied
    asked = prosper_model.asked["tidy"][0][1]["content"]
    assert "we are closed" in asked and f"call {calls[1]['id']} · " in asked
    # Nothing changes until the person keeps it.
    before = client.get(f"/api/agents/{agent_id}/issues/{number}").json()
    assert before["title"] == COMPLAINT["title"]

    kept = client.patch(
        f"/api/agents/{agent_id}/issues/{number}", json={**tidied, "tidied": True}
    ).json()
    assert (kept["title"], kept["step"], kept["severity"], kept["calls"]) == (
        "Books appointments on Sundays",
        "offer_times",
        "booking",
        1,
    )
    assert kept["description"] == COMPLAINT["description"]  # their words stay
    assert (kept["events"][-1]["type"], kept["events"][-1]["by"]) == ("tidied", "Prosper AI")

    edited = client.patch(
        f"/api/agents/{agent_id}/issues/{number}", json={"step": "", "severity": None}
    ).json()
    assert (edited["step"], edited["severity"], edited["title"]) == ("", None, kept["title"])
    assert (edited["events"][-1]["type"], edited["events"][-1]["by"]) == ("edited", "you")


def test_an_issue_found_in_calls_is_not_edited_or_tidied(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {"callers": [CALLERS], "audit": [copy.deepcopy(REVIEW)] * 2}
    prosper_model.script["grouping"] = [{"placements": [{"finding": 0, "issue": 2}]}]
    client.post(f"/api/agents/{agent_id}/calls/play")
    settle()
    path = f"/api/agents/{agent_id}/issues/2"
    assert client.patch(path, json={"title": "Mine"}).status_code == 409
    assert client.post(f"{path}/tidy").status_code == 409


def test_prosper_ai_fixes_a_reported_issue_with_no_calls(
    client, live_agent, prosper_model, verdicts
):
    agent_id = live_agent()
    number = _report(client, agent_id)["number"]
    prosper_model.script = {"reproduce": [TEST], "fix": [FIX]}
    verdicts += [False, False, False]  # the test fails on v1

    opened = client.post(f"/api/agents/{agent_id}/issues/{number}/fix", json={"prosper": True})
    assert opened.status_code == 201, opened.text
    settle()
    pull = client.get(f"/api/agents/{agent_id}/pulls/{opened.json()['number']}").json()

    assert pull["title"] == "Fix: Patient booked on a Sunday"
    assert [e["type"] for e in pull["events"]] == [
        "opened",
        "reproduced",
        "proposed",
        "rule",
        "checks",
        "proved",
    ]
    assert pull["events"][1]["text"] == (
        "Reproduced it: a test that calls like the one reported fails on v1 · 0/3"
    )
    # The caller is written from what the clinic said.
    [asked] = prosper_model.asked["reproduce"]
    assert "reported by the clinic (step not known)" in asked[1]["content"]
    assert "we are closed" in asked[1]["content"]
    assert "It has no calls" in asked[1]["content"]

    merged = client.post(f"/api/agents/{agent_id}/pulls/{pull['number']}/merge")
    assert merged.status_code == 200, merged.text
    issue = client.get(f"/api/agents/{agent_id}/issues/{number}").json()
    assert (issue["state"], issue["fixed"]) == ("resolved", {"pull": pull["number"], "version": 2})


def test_a_finding_from_calls_joins_a_reported_issue(client, live_agent, prosper_model):
    agent_id = live_agent()
    number = _report(client, agent_id)["number"]
    prosper_model.script = {
        "callers": [CALLERS],
        "audit": [copy.deepcopy(REVIEW), copy.deepcopy(REVIEW)],
        # Each call's finding is the clinic's complaint.
        "grouping": [{"placements": [{"finding": 0, "issue": number}]}] * 2,
    }
    client.post(f"/api/agents/{agent_id}/calls/play")
    settle()

    [issue] = client.get(f"/api/agents/{agent_id}/issues").json()
    assert (issue["number"], issue["calls"], issue["reported"]) == (number, 2, "clinic")
    assert issue["title"] == COMPLAINT["title"]  # the person's words stay
    assert issue["step"] == "offer_times"  # learned from the first call
    grouping = prosper_model.asked["grouping"][0][1]["content"]
    assert f"[{number}] step not known · Patient booked on a Sunday" in grouping
    assert "(reported by a person)" in grouping
    events = store.issues.get_issue(agent_id, number)["events"]
    assert [e["type"] for e in events] == ["reported", "seen", "seen"]
