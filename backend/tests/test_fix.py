#
# Fixing an issue, through the API: "Fix with Prosper AI" opens a pull request
# where Prosper AI reproduces the issue with a test, proposes the smallest
# change and proves it on the whole suite; merging it resolves the issue, and
# a call on the fixed version with the same problem opens it again. "Fix it
# yourself" opens the same kind of pull request for the person. The model is
# scripted and the calls run on fakes: nothing here reaches OpenAI.
#
# The fake judge decides the test that reproduces the issue: its verdicts are
# given in order, so a test can fail on the version with the issue and pass on
# the fix (the reproduction runs before the suite does).
#

import copy
import json
from pathlib import Path

import pytest

import store
from copilot import artifacts, audit
from tests.conftest import settle
from tests.test_live import CALLERS, REVIEW

EXAMPLE = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())
ISSUE = 2  # PR #1 took number 1; the first issue is #2

TEST = {
    "name": "Offers only open times",
    "caller": "You are Ana Ruiz and you want a check-up on Thursday afternoon.",
    "checks": ["Reaches Offer times", "Offers only times the clinic is open"],
}
RULE = {"step": "Offer times", "text": "Offer only Tuesday at 10 AM."}
FIX = {
    "reply": "Added a rule in Offer times: offer only Tuesday at 10 AM, as the clinic is "
    "closed on Thursday afternoons.",
    "agent": artifacts.from_config(EXAMPLE),
    "rules": [RULE],
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


@pytest.fixture
def with_issue(client, live_agent, prosper_model):
    """A live agent whose calls found one issue (#2): returns its id."""

    def make() -> str:
        agent_id = live_agent()
        prosper_model.script = {
            "callers": [CALLERS],
            # Both callers hit the same problem: one issue, two calls.
            "audit": [copy.deepcopy(REVIEW), copy.deepcopy(REVIEW)],
            "grouping": [{"placements": [{"finding": 0, "issue": ISSUE}]}],
        }
        client.post(f"/api/agents/{agent_id}/calls/play")
        settle()
        return agent_id

    return make


def _fix(client, agent_id, prosper=True, status=201) -> dict:
    response = client.post(f"/api/agents/{agent_id}/issues/{ISSUE}/fix", json={"prosper": prosper})
    assert response.status_code == status, response.text
    settle()
    return response.json()


def _pull(client, agent_id, number) -> dict:
    return client.get(f"/api/agents/{agent_id}/pulls/{number}").json()


def _issue(client, agent_id) -> dict:
    return client.get(f"/api/agents/{agent_id}/issues/{ISSUE}").json()


def _types(pull: dict) -> list[str]:
    return [event["type"] for event in pull["events"]]


def test_prosper_ai_reproduces_the_issue_proposes_a_fix_and_proves_it(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST], "fix": [FIX]}
    verdicts += [False, False, False]  # the test fails on v1, all three calls

    opened = _fix(client, agent_id)
    pull = _pull(client, agent_id, opened["number"])

    assert (pull["kind"], pull["fixes"], pull["base_version"]) == ("fix", ISSUE, 1)
    assert pull["title"] == "Fix: Offers Thursday afternoons"
    assert _types(pull) == ["opened", "reproduced", "proposed", "rule", "checks", "proved"]
    reproduced = pull["events"][1]
    assert reproduced["text"] == (
        "Reproduced it: a test that calls like these 2 callers fails on v1 · 0/3"
    )
    assert (reproduced["passed"], reproduced["total"], reproduced["version"]) == (0, 3, 1)
    [test] = pull["tests"]
    assert test["id"] == reproduced["test"]
    assert test["source"] == {
        "kind": "issue",
        "pull": opened["number"],
        "issue": ISSUE,
        "file": None,
        "quote": None,
        "before": {"version": 1, "passed": 0, "runs": 3},
    }
    [rule] = pull["rules"]
    assert (rule["step"], rule["source"]["kind"]) == ("offer_times", "issue")
    assert pull["events"][2]["text"].startswith("Added a rule in Offer times")
    assert pull["checks"]["state"] == "passed"
    assert pull["events"][-1]["text"] == (
        "All checks passed · 1/1 · 3 runs each · the new test 0/3 on v1 → 3/3"
    )
    assert pull["prosper"]["state"] == "done"

    # What it was asked: the issue, and its call up to the bad turn.
    [asked] = prosper_model.asked["reproduce"]
    assert "Offers Thursday afternoons" in asked[1]["content"]
    assert "Ana Ruiz, on v1" in asked[1]["content"]
    assert "Tom Lee, on v1" in asked[1]["content"]
    [proposal] = prosper_model.asked["fix"]
    assert "on v1: passed 0 of 3 calls" in proposal[1]["content"]

    issue = _issue(client, agent_id)
    assert issue["state"] == "open"
    assert issue["pulls"] == [
        {
            "number": opened["number"],
            "title": pull["title"],
            "state": "open",
            "merged_version": None,
        }
    ]
    assert (issue["events"][-1]["type"], issue["events"][-1]["pull"]) == ("fixing", 3)


def test_a_test_that_passes_is_tried_again_with_a_sharper_caller(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    sharper = {**TEST, "caller": "You are Ana Ruiz and insist on Thursday at 2 PM."}
    prosper_model.script = {"reproduce": [TEST, sharper], "fix": [FIX]}
    verdicts += [True, True, True, False, False, True]

    pull = _pull(client, agent_id, _fix(client, agent_id)["number"])

    assert _types(pull)[:3] == ["opened", "step", "reproduced"]
    assert pull["events"][1]["text"] == "A first test passed 3/3 on v1: trying a sharper caller"
    assert pull["events"][2]["text"].endswith("fails on v1 · 1/3")
    assert pull["tests"][0]["caller"] == sharper["caller"]
    # The second request was told how the first test went.
    second = prosper_model.asked["reproduce"][1][1]["content"]
    assert "passed 3 of 3 calls on v1" in second


def test_when_it_cannot_reproduce_it_says_so_and_asks_whether_to_go_on(
    client, with_issue, prosper_model
):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST, TEST], "fix": [FIX]}

    number = _fix(client, agent_id)["number"]
    pull = _pull(client, agent_id, number)

    assert _types(pull)[-3:] == ["step", "message", "question"]
    assert pull["events"][-2]["text"] == (
        "Could not reproduce it on v1: 3/3. It may be rare or already fixed."
    )
    assert pull["prosper"]["state"] == "waiting"
    assert pull["tests"] == []
    # Nothing merges while it waits for the answer.
    assert client.post(f"/api/agents/{agent_id}/pulls/{number}/merge").status_code == 409

    question = pull["events"][-1]["question"]
    answer = {"question": question, "option": 0}
    client.post(f"/api/agents/{agent_id}/pulls/{number}/answers", json=answer)
    settle()

    pull = _pull(client, agent_id, number)
    assert _types(pull)[-7:] == [
        "question",
        "answer",
        "step",
        "proposed",
        "rule",
        "checks",
        "proved",
    ]
    assert pull["events"][-5]["text"] == "Added the test anyway: 3/3 on v1"
    assert pull["tests"][0]["source"]["before"] == {"version": 1, "passed": 3, "runs": 3}


def test_told_to_stop_it_leaves_the_copy_as_it_is(client, with_issue, prosper_model):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST, TEST]}
    number = _fix(client, agent_id)["number"]
    question = _pull(client, agent_id, number)["events"][-1]["question"]

    client.post(
        f"/api/agents/{agent_id}/pulls/{number}/answers", json={"question": question, "option": 1}
    )
    settle()

    pull = _pull(client, agent_id, number)
    assert pull["events"][-1]["text"].startswith("Left it as it is: v1 stays unchanged.")
    assert pull["prosper"]["state"] == "done"
    assert (pull["tests"], pull["rules"]) == ([], [])


def test_merging_the_fix_resolves_the_issue_in_the_new_version(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST], "fix": [FIX]}
    verdicts += [False] * 3
    number = _fix(client, agent_id)["number"]

    merged = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge")
    assert merged.status_code == 200, merged.text

    issue = _issue(client, agent_id)
    assert issue["state"] == "resolved"
    assert issue["fixed"] == {"pull": number, "version": 2}
    assert (issue["events"][-1]["type"], issue["events"][-1]["version"]) == ("fixed", 2)
    assert issue["events"][-1]["by"] == "you"  # who merged it, as merge_pull was told

    assert issue["pulls"][0]["merged_version"] == 2
    # Its test stays in the suite.
    assert store.get_version(agent_id, 2)["tests"][0]["source"]["issue"] == ISSUE


def test_whoever_merges_the_fix_is_who_resolved_the_issue(client, with_issue):
    agent_id = with_issue()
    number = _fix(client, agent_id, prosper=False)["number"]
    with store.db.connect() as conn:
        store.issues.resolve_by_fix(conn, agent_id, ISSUE, number, 2, "Ana")
    assert _issue(client, agent_id)["events"][-1]["by"] == "Ana"


def test_closing_the_fix_unlinks_it_and_reopening_links_it_again(client, with_issue):
    agent_id = with_issue()
    number = _fix(client, agent_id, prosper=False)["number"]
    # One fix at a time.
    assert (
        _fix(client, agent_id, status=409)["detail"] == f"PR #{number} is fixing Issue #2 already."
    )

    client.post(f"/api/agents/{agent_id}/pulls/{number}/close")
    issue = _issue(client, agent_id)
    assert issue["state"] == "open"
    assert issue["pulls"][0]["state"] == "closed"
    assert issue["events"][-1]["type"] == "unlinked"

    client.post(f"/api/agents/{agent_id}/pulls/{number}/reopen")
    assert _issue(client, agent_id)["events"][-1]["type"] == "relinked"


def test_fix_it_yourself_opens_a_fix_without_prosper_ai(client, with_issue):
    agent_id = with_issue()
    pull = _fix(client, agent_id, prosper=False)
    assert (pull["kind"], pull["fixes"], pull["prosper"]) == ("fix", ISSUE, None)
    assert pull["events"][0] == {**pull["events"][0], "by": "you", "issue": ISSUE, "version": 1}
    assert _issue(client, agent_id)["events"][-1]["by"] == "you"


def test_a_resolved_or_ignored_issue_is_not_fixed(client, with_issue):
    agent_id = with_issue()
    client.post(f"/api/agents/{agent_id}/issues/{ISSUE}/ignore")
    assert "ignored" in _fix(client, agent_id, status=409)["detail"]
    assert (
        client.post(f"/api/agents/{agent_id}/issues/9/fix", json={"prosper": False}).status_code
        == 404
    )


def _call_on(agent_id: str, version: int) -> int:
    call = {"path": [], "transcript": [{"role": "agent", "text": "Hi.", "node": None}]}
    return store.calls.add_call(
        agent_id, None, version, "Ana", "A caller.", {**call, "ended": "x"}, 5, {}
    )


def test_the_same_problem_on_the_fixed_version_opens_the_issue_again(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST], "fix": [FIX]}
    verdicts += [False] * 3
    number = _fix(client, agent_id)["number"]
    client.post(f"/api/agents/{agent_id}/pulls/{number}/merge")
    finding = {"check": "c", "step": "greeting", "turn": 0, "quote": "Hi", "why": "w"}

    # A v1 call reviewed after the merge: the problem it had is the one fixed.
    assert ISSUE in [i["number"] for i in store.issues.joinable(agent_id)]
    store.issues.file_finding(agent_id, _call_on(agent_id, 1), "Ana", finding, ISSUE)
    issue = _issue(client, agent_id)
    assert (issue["state"], issue["events"][-1]["type"]) == ("resolved", "seen")

    store.issues.file_finding(agent_id, _call_on(agent_id, 2), "Ana", finding, ISSUE)
    issue = _issue(client, agent_id)
    assert issue["state"] == "open"
    assert (issue["events"][-1]["type"], issue["events"][-1]["text"]) == ("came_back", "v2")
    assert issue["fixed"] is None


def test_an_issue_resolved_by_hand_is_not_joined(client, with_issue):
    agent_id = with_issue()
    client.post(f"/api/agents/{agent_id}/issues/{ISSUE}/resolve")
    assert store.issues.joinable(agent_id) == []


def test_a_message_refines_the_fix_and_the_checks_run_again(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    phone = {"step": "Collect details", "text": "If they don't know it, ask for their phone."}
    change = {"reply": "Added a rule in Collect details.", "agent": FIX["agent"], "rules": [phone]}
    prosper_model.script = {
        "reproduce": [TEST],
        "fix": [FIX],
        "change": [{**change, "tests": [], "remove": []}],
    }
    verdicts += [False] * 3
    number = _fix(client, agent_id)["number"]

    client.post(
        f"/api/agents/{agent_id}/pulls/{number}/messages",
        json={"text": "If they don't know it, use their phone number"},
    )
    settle()

    pull = _pull(client, agent_id, number)
    assert _types(pull)[-5:] == ["message", "message", "rule", "checks", "proved"]
    assert len(pull["rules"]) == 2
    # The request knew which issue it fixes.
    assert "This pull request fixes Issue #2" in prosper_model.asked["change"][0][1]["content"]


def test_prosper_ai_takes_a_message_on_any_open_pull_request(client, live_agent, prosper_model):
    agent_id = live_agent()
    number = client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Mine"}).json()["number"]
    change = {"reply": "Added a rule.", "agent": FIX["agent"], "rules": [RULE]}
    prosper_model.script = {"change": [{**change, "tests": [], "remove": []}]}

    response = client.post(
        f"/api/agents/{agent_id}/pulls/{number}/messages", json={"text": "Only Tuesdays"}
    )
    assert response.status_code == 200
    settle()

    pull = _pull(client, agent_id, number)
    assert [r["text"] for r in pull["rules"]] == [RULE["text"]]
    assert pull["prosper"]["state"] == "done"
    # Hand-drawn: no guidelines to read, and its functions keep their names.
    assert "No written guidelines" in prosper_model.asked["change"][0][1]["content"]
    assert pull["config"] == EXAMPLE | {"name": "Dental Recall"}


# ---- what a fix is held to ------------------------------------------------------


def test_a_fix_changes_something_and_two_steps_at_most():
    nothing = {**FIX, "rules": []}
    with pytest.raises(ValueError, match="Nothing changed"):
        artifacts.check_fix(nothing, EXAMPLE)
    agent = copy.deepcopy(FIX["agent"])
    for node in agent["nodes"][:3]:
        node["task"] = "Say hi."
    with pytest.raises(ValueError, match="changes 3 steps"):
        artifacts.check_fix({**FIX, "agent": agent}, EXAMPLE)
    assert artifacts.check_fix(FIX, EXAMPLE) == EXAMPLE


def test_the_test_that_reproduces_the_issue_is_never_rewritten():
    answer = {
        "summary": "s",
        "verdicts": [{"test": "t1", "verdict": "test", "why": "w"}],
        "agent": FIX["agent"],
        "rules": [],
        "remove_rules": [],
        "tests": [{"id": "t1", **TEST}],
        "questions": [],
    }
    with pytest.raises(ValueError, match="reproduces the issue"):
        artifacts.check_review(answer, {"t1": "Offers"}, EXAMPLE, set(), {"t1"})


def test_a_new_message_gets_its_own_rounds_of_checking(client, live_agent):
    agent_id = live_agent()
    number = client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Mine"}).json()["number"]
    store.prosper.update(agent_id, number, state="done", rounds=2, handed_over=True)

    store.prosper.take_message(agent_id, number, "Only Tuesdays")

    work = store.prosper.work_of(agent_id, number)
    assert "rounds" not in work and "handed_over" not in work


@pytest.mark.parametrize("state", ["ignore", "resolve"])
def test_merging_a_fix_leaves_an_issue_the_person_closed_as_they_left_it(
    client, with_issue, state
):
    agent_id = with_issue()
    number = _fix(client, agent_id, prosper=False)["number"]
    client.post(f"/api/agents/{agent_id}/issues/{ISSUE}/{state}")
    left = _issue(client, agent_id)

    with store.db.connect() as conn:
        store.issues.resolve_by_fix(conn, agent_id, ISSUE, number, 2, "you")

    issue = _issue(client, agent_id)
    assert (issue["state"], issue["fixed"]) == (left["state"], None)
    merged = issue["events"][-1]
    assert (merged["type"], merged["pull"], merged["version"]) == ("fix_merged", number, 2)
    assert merged["text"] == left["state"]


def test_going_on_without_the_test_it_wrote_says_so_and_stops(client, with_issue, prosper_model):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST, TEST]}
    number = _fix(client, agent_id)["number"]
    question = _pull(client, agent_id, number)["events"][-1]["question"]
    store.prosper.update(agent_id, number, candidate=None)  # the record lost it

    answer = {"question": question, "option": 0}
    client.post(f"/api/agents/{agent_id}/pulls/{number}/answers", json=answer)
    settle()

    pull = _pull(client, agent_id, number)
    assert pull["events"][-1]["text"].startswith("I no longer have the test I wrote on v1")
    assert pull["prosper"]["state"] == "done"
    assert pull["tests"] == []


# ---- A fix that may not fix its issue: warned of, never blocked ---------------------


@pytest.fixture
def fixed_at(client, with_issue, prosper_model, verdicts, monkeypatch):
    """A fix whose own test (id "repro") fails on v1, then scores `after` (one list per run
    of the suite). Returns (agent id, pull)."""
    from copilot import fix

    monkeypatch.setattr(fix, "new_id", lambda: "repro")

    def make(*after: list[bool]) -> tuple[str, dict]:
        agent_id = with_issue()
        prosper_model.script = {"reproduce": [TEST], "fix": [FIX]}
        verdicts.extend([False] * 3)
        for run in after:
            verdicts.extend(run)
        number = _fix(client, agent_id)["number"]
        return agent_id, _pull(client, agent_id, number)

    return make


def test_a_fix_whose_test_passes_three_of_three_merges_with_no_warning(client, fixed_at):
    agent_id, pull = fixed_at([True] * 3)

    assert pull["warnings"] == []
    merged = client.post(f"/api/agents/{agent_id}/pulls/{pull['number']}/merge")
    assert merged.status_code == 200, merged.text
    assert _issue(client, agent_id)["events"][-1]["text"] is None


def test_a_fix_whose_test_passes_two_of_three_warns_and_asks_to_confirm(client, fixed_at):
    agent_id, pull = fixed_at([False, True, True])
    number = pull["number"]

    assert pull["checks"]["state"] == "passed"
    warning = (
        f"The test for Issue #{ISSUE} passes 2 of 3: the problem may still happen in some calls."
    )
    assert pull["warnings"] == [warning]
    refused = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge")
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"{warning} Merge anyway to go on."
    merged = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge", json={"anyway": True})
    assert merged.status_code == 200, merged.text

    issue = _issue(client, agent_id)
    assert issue["state"] == "resolved"
    assert issue["events"][-1]["text"] == "merged with its test at 2/3"


def test_a_fix_not_reproduced_warns_and_asks_to_confirm(client, with_issue, prosper_model):
    agent_id = with_issue()
    prosper_model.script = {"reproduce": [TEST, TEST], "fix": [FIX]}
    number = _fix(client, agent_id)["number"]
    question = _pull(client, agent_id, number)["events"][-1]["question"]
    client.post(
        f"/api/agents/{agent_id}/pulls/{number}/answers", json={"question": question, "option": 0}
    )
    settle()

    pull = _pull(client, agent_id, number)
    assert pull["checks"]["state"] == "passed"
    assert pull["warnings"] == ["Not reproduced on v1: nothing shows this change fixes it."]
    assert client.post(f"/api/agents/{agent_id}/pulls/{number}/merge").status_code == 409
    merged = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge", json={"anyway": True})
    assert merged.status_code == 200
    assert _issue(client, agent_id)["events"][-1]["text"] == "merged without reproducing it on v1"
