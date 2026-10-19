#
# Calls coming in and the issues Prosper AI files from them, through the API:
# the callers, the review and the grouping come from a scripted model, the
# calls from the scripted booking (tests/fakes.py). Nothing reaches OpenAI.
#

import copy

import pytest

from copilot import audit, calls
from tests.conftest import settle

# The scripted booking, as a text call writes it down: the agent's lines are 0, 2, 4 and 6.
OFFER = 4  # "I can offer Tuesday at 10 AM or Thursday at 2 PM.", said in offer_times

CALLERS = {
    "callers": [
        {"name": "Ana Ruiz", "kind": "routine", "situation": "You are Ana Ruiz, for a check-up."},
        {"name": "Tom Lee", "kind": "edge", "situation": "You are Tom Lee and have chest pain."},
    ]
}
REVIEW = {
    "outcome": "booked",
    "checks": [
        {"text": "Greets the caller", "passed": True, "rule": ""},
        {"text": "Asks for the name before booking", "passed": True, "rule": ""},
        {"text": "Offers only times the clinic is open", "passed": False, "rule": ""},
    ],
    "findings": [
        {
            "check": "Offers only times the clinic is open",
            "turn": OFFER,
            "quote": "Thursday at 2 PM",
            "why": "The clinic closes at noon on Thursdays.",
            "title": "Offers Thursday afternoons",
            "severity": "booking",
            "description": "The agent offers slots when the clinic is closed.",
        }
    ],
}
CLEAN = {"outcome": "booked", "checks": REVIEW["checks"][:2], "findings": []}


@pytest.fixture(autouse=True)
def two_callers(monkeypatch):
    # A batch of two, so each test scripts two reviews.
    monkeypatch.setattr(audit, "CALLERS_PER_BATCH", (2, 2))


def _play(client, agent_id):
    response = client.post(f"/api/agents/{agent_id}/calls/play")
    assert response.status_code == 202, response.text
    settle()
    return client.get(f"/api/agents/{agent_id}/calls").json()


def test_calls_come_in_on_live_and_the_same_problem_is_one_issue(
    client, live_agent, prosper_model
):
    agent_id = live_agent()
    prosper_model.script = {
        "callers": [CALLERS],
        "audit": [copy.deepcopy(REVIEW), copy.deepcopy(REVIEW)],
        # The second call's finding may join the issue the first one opened.
        "grouping": [{"placements": [{"finding": 0, "issue": 2}]}],
    }
    page = _play(client, agent_id)

    assert page["play"]["state"] == "done"
    assert page["play"]["callers"] == 2
    calls = page["calls"]
    assert sorted(call["caller"] for call in calls) == ["Ana Ruiz", "Tom Lee"]
    assert {call["version"] for call in calls} == {1}
    assert all(call["review"] == "done" and call["outcome"] == "booked" for call in calls)
    assert all(call["issues"] == [2] for call in calls)  # PR #1 took number 1
    assert all(call["seconds"] > 0 for call in calls)

    [issue] = client.get(f"/api/agents/{agent_id}/issues").json()
    assert issue["title"] == "Offers Thursday afternoons"
    assert issue["step"] == "offer_times"  # where the agent said the quoted line
    assert issue["calls"] == 2
    assert client.get(f"/api/agents/{agent_id}").json()["open_issues"] == 1

    full = client.get(f"/api/agents/{agent_id}/issues/2").json()
    assert [line["index"] for line in full["findings"][0]["lines"]] == [OFFER - 1, OFFER]
    assert [event["type"] for event in full["events"]] == ["opened", "seen"]

    call = client.get(f"/api/agents/{agent_id}/calls/{calls[0]['id']}").json()
    assert call["findings"][0]["issue"] == 2
    assert [c["passed"] for c in call["checks"]] == [True, True, False]
    # What the grouping was shown: the issue it could join, in that step.
    [grouping] = prosper_model.asked["grouping"]
    assert "[2] offer_times · Offers Thursday afternoons" in grouping[1]["content"]


def test_a_different_problem_opens_its_own_issue(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {
        "callers": [CALLERS],
        "audit": [copy.deepcopy(REVIEW), copy.deepcopy(REVIEW)],
        "grouping": [{"placements": [{"finding": 0, "issue": 0}]}],
    }
    _play(client, agent_id)
    issues = client.get(f"/api/agents/{agent_id}/issues").json()
    assert [issue["number"] for issue in issues] == [3, 2]


def test_an_issue_resolved_while_the_batch_runs_takes_no_more_calls(
    client, live_agent, prosper_model, monkeypatch
):
    agent_id = live_agent()
    prosper_model.script = {
        "callers": [CALLERS],
        "audit": [copy.deepcopy(REVIEW), copy.deepcopy(REVIEW)],
        "grouping": [{"placements": [{"finding": 0, "issue": 2}]}],
    }
    grouped = calls._group

    def then_resolved(llm, agent, findings):
        # The person resolves #2 after the second call was grouped into it,
        # before its findings are filed.
        placed = grouped(llm, agent, findings)
        if placed == [2]:
            client.post(f"/api/agents/{agent}/issues/2/resolve")
        return placed

    monkeypatch.setattr(calls, "_group", then_resolved)
    page = _play(client, agent_id)

    assert all(call["review"] == "done" for call in page["calls"])
    assert sorted(call["issues"] for call in page["calls"]) == [[2], [3]]
    issues = {i["number"]: i for i in client.get(f"/api/agents/{agent_id}/issues").json()}
    assert (issues[2]["state"], issues[2]["calls"]) == ("resolved", 1)
    assert (issues[3]["state"], issues[3]["calls"]) == ("open", 1)
    # The review landed with its findings: the call shows its checks.
    second = next(c for c in page["calls"] if c["issues"] == [3])
    call = client.get(f"/api/agents/{agent_id}/calls/{second['id']}").json()
    assert [c["passed"] for c in call["checks"]] == [True, True, False]


def test_a_batch_where_no_call_ran_fails_and_says_why(
    client, live_agent, prosper_model, fake_checks
):
    agent_id = live_agent()
    prosper_model.script = {"callers": [CALLERS]}

    def down(model):
        raise RuntimeError("The model is down.")

    fake_checks.llm = down
    page = _play(client, agent_id)
    assert page["calls"] == []
    assert page["play"]["state"] == "failed"
    assert page["play"]["error"] == "None of the 2 calls ran: The model is down."


def test_a_clean_call_files_nothing_and_asks_no_grouping(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {"callers": [CALLERS], "audit": [CLEAN, copy.deepcopy(CLEAN)]}
    page = _play(client, agent_id)
    assert all(call["issues"] == [] for call in page["calls"])
    assert "grouping" not in prosper_model.asked
    assert client.get(f"/api/agents/{agent_id}/issues").json() == []


def test_a_review_that_fails_leaves_the_call_unreviewed(client, live_agent, prosper_model):
    agent_id = live_agent()
    bad = {**copy.deepcopy(REVIEW), "findings": []}  # a failed check with no finding
    prosper_model.script = {"callers": [CALLERS], "audit": [bad] * 6}
    page = _play(client, agent_id)
    assert {call["review"] for call in page["calls"]} == {"failed"}
    assert page["play"]["state"] == "done"


def test_calls_need_a_live_version_and_one_batch_at_a_time(client, new_agent):
    agent_id, _ = new_agent("Draft")
    response = client.post(f"/api/agents/{agent_id}/calls/play")
    assert response.status_code == 409
    assert "not live" in response.json()["detail"]
    assert client.post("/api/agents/nope/calls/play").status_code == 404


def test_an_issue_is_snoozed_resolved_ignored_and_reopened(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {
        "callers": [CALLERS],
        "audit": [copy.deepcopy(REVIEW), copy.deepcopy(CLEAN)],
    }
    _play(client, agent_id)
    base = f"/api/agents/{agent_id}/issues/2"
    snoozed = client.post(f"{base}/snooze", json={"until": "week"}).json()
    assert snoozed["state"] == "snoozed" and "until" in snoozed["snooze"]
    assert client.post(f"{base}/snooze", json={"until": "day"}).status_code == 409
    assert client.post(f"{base}/resolve").json()["state"] == "resolved"
    assert client.post(f"{base}/reopen").json()["state"] == "open"
    ignored = client.post(f"{base}/ignore").json()
    assert ignored["state"] == "ignored"
    assert [e["type"] for e in ignored["events"]][1:] == [
        "snoozed",
        "resolved",
        "reopened",
        "ignored",
    ]
    assert client.get(f"/api/agents/{agent_id}/issues/9").status_code == 404


# ---- what the model's answers are held to -------------------------------------

TRANSCRIPT = [
    {"role": "agent", "text": "Hi, how can I help?", "node": "greeting"},
    {"role": "caller", "text": "A check-up, please.", "node": "greeting"},
    {"role": "agent", "text": "I can offer Thursday at 2 PM.", "node": "offer_times"},
]


def _review(**finding):
    review = copy.deepcopy(REVIEW)
    review["findings"][0].update({"turn": 2, **finding})
    return review


@pytest.mark.parametrize(
    "review, problem",
    [
        (_review(turn=1), "not a line of the agent"),
        (_review(turn=7), "not a line of the agent"),
        (_review(quote="Saturday at 9"), "word for word"),
        (_review(check="Something else"), "not a failed check"),
        ({**_review(), "findings": []}, "give it a finding"),
        (_review(why="It matters. A lot."), "one sentence"),
    ],
)
def test_a_finding_points_at_a_real_turn_of_the_agent(review, problem):
    with pytest.raises(ValueError, match=problem):
        audit.check_audit(review, TRANSCRIPT, set())


def test_a_check_names_only_rules_the_agent_has():
    review = _review()
    review["checks"][0]["rule"] = "r1"
    audit.check_audit(review, TRANSCRIPT, {"r1"})
    with pytest.raises(ValueError, match="does not have"):
        audit.check_audit(review, TRANSCRIPT, {"r2"})


def test_a_finding_joins_only_an_issue_it_may_join():
    audit.check_grouping({"placements": [{"finding": 0, "issue": 4}]}, {0: [4]})
    audit.check_grouping({"placements": [{"finding": 0, "issue": 0}]}, {0: [4]})
    with pytest.raises(ValueError, match="cannot join"):
        audit.check_grouping({"placements": [{"finding": 0, "issue": 5}]}, {0: [4]})
    with pytest.raises(ValueError, match="exactly once"):
        audit.check_grouping({"placements": []}, {0: [4]})


def test_a_batch_is_mostly_routine_callers_with_distinct_names():
    def batch(edge: int, total: int = 10, same: bool = False):
        return {
            "callers": [
                {
                    "name": "Ana" if same else f"Caller {i}",
                    "kind": "edge" if i < edge else "routine",
                    "situation": "You are...",
                }
                for i in range(total)
            ]
        }

    audit.check_callers(batch(3))
    with pytest.raises(ValueError, match="edge cases"):
        audit.check_callers(batch(0))
    with pytest.raises(ValueError, match="edge cases"):
        audit.check_callers(batch(6))
    with pytest.raises(ValueError, match="different name"):
        audit.check_callers(batch(3, same=True))
    with pytest.raises(ValueError, match="10 to 12"):
        audit.check_callers(batch(3, total=8))


def test_a_call_lasts_what_its_words_would_take_to_say():
    assert audit.seconds(TRANSCRIPT) == round(15 / 2.5 + 0.8 * 3)
