#
# Fixing an issue, through the API: "Fix with Prosper AI" opens a pull request
# where Prosper AI reproduces the issue with a test, makes the smallest change
# and proves it on the whole suite; merging it resolves the issue, and a call
# on the fixed version with the same problem opens it again. "Fix it
# yourself" opens the same kind of pull request for the person. The guards of
# a fix are its tools': nothing changes before the issue is reproduced (or the
# person says to go on), its own test stays as it is, two steps at most.
#
# Prosper AI's model is scripted (each answer a tool call or its last word)
# and the calls run on fakes: nothing here reaches OpenAI. The fake judge
# decides the test that reproduces the issue: its verdicts are given in
# order, so a test can fail on the version with the issue and pass on the fix
# (the reproduction runs before the suite does).
#

import copy
import json
from pathlib import Path

import pytest

import store
from api.tools import TOOLS
from copilot import agent as prosper
from copilot import audit, work
from copilot.agent import Work
from tests.conftest import settle
from tests.fakes import tool
from tests.test_live import CALLERS, REVIEW

EXAMPLE = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())
ISSUE = 2  # PR #1 took number 1; the first issue is #2

TEST = {
    "name": "Offers only open times",
    "caller": "You are Ana Ruiz and you want a check-up on Thursday afternoon.",
    "checks": ["Reaches Offer times", "Offers only times the clinic is open"],
}
RULE = {"step": "Offer times", "text": "Offer only Tuesday at 10 AM."}
SAID = (
    "Added a rule in Offer times: offer only Tuesday at 10 AM, as the clinic is closed on "
    "Thursday afternoons."
)
END = {"answer": "All checks pass, and the new test went from 0/3 to 3/3. Merge it.", "links": []}
# A fix as Prosper AI makes it: reproduce, a rule, the suite, its last word.
FIX = [
    tool("reproduce", **TEST),
    tool("add_rules", rules=[{**RULE, "source": None, "quote": None}]),
    tool("run_all", said=SAID),
    END,
]


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


def _script(model, *steps) -> None:
    model.script = {"work": list(steps)}


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


def _told(model, turn: int = -1) -> str:
    """What a turn of the work started from: the facts, its first message."""
    return [asked for asked in model.asked["work"] if len(asked) == 2][turn][1]["content"]


def _outputs(model) -> list[str]:
    return [asked[-1]["output"] for asked in model.asked["work"] if "output" in asked[-1]]


def _answer(client, agent_id, number, option: int) -> None:
    question = _pull(client, agent_id, number)["events"][-1]["question"]
    answer = {"question": question, "option": option}
    assert (
        client.post(f"/api/agents/{agent_id}/pulls/{number}/answers", json=answer).status_code
        == 200
    )
    settle()


def test_prosper_ai_reproduces_the_issue_makes_a_fix_and_proves_it(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    _script(prosper_model, *FIX)
    verdicts += [False, False, False]  # the test fails on v1, all three calls

    opened = _fix(client, agent_id)
    pull = _pull(client, agent_id, opened["number"])

    assert (pull["kind"], pull["fixes"], pull["base_version"]) == ("fix", ISSUE, 1)
    assert pull["title"] == "Fix: Offers Thursday afternoons"
    assert _types(pull) == [
        "opened",
        "reproduced",
        "proposed",
        "rule",
        "checks",
        "proved",
        "message",
    ]
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
    proposed = pull["events"][2]
    assert (proposed["text"], proposed["changed"]) == (SAID, True)
    assert pull["checks"]["state"] == "passed"
    assert pull["events"][-2]["text"] == (
        "All checks passed · 1/1 · 3 runs each · the new test 0/3 on v1 → 3/3"
    )
    assert pull["events"][-1]["text"] == END["answer"]
    assert pull["prosper"]["state"] == "done"
    assert pull["warnings"] == []

    # What it started from: the issue, and its calls up to the bad turn.
    facts = _told(prosper_model)
    assert "What it fixes: Issue #2" in facts and "Offers Thursday afternoons" in facts
    assert "Ana Ruiz, on v1" in facts and "Tom Lee, on v1" in facts
    assert "Not reproduced yet: 2 tries left on v1." in facts
    # Told what reproducing did, before it changed anything.
    assert _outputs(prosper_model)[0].startswith("Reproduced: it fails on v1, 0/3.")

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
    _script(prosper_model, FIX[0], tool("reproduce", **sharper), *FIX[1:])
    verdicts += [True, True, True, False, False, True]

    pull = _pull(client, agent_id, _fix(client, agent_id)["number"])

    assert _types(pull)[:3] == ["opened", "step", "reproduced"]
    assert pull["events"][1]["text"] == "A first test passed 3/3 on v1: trying a sharper caller"
    assert pull["events"][2]["text"].endswith("fails on v1 · 1/3")
    assert pull["tests"][0]["caller"] == sharper["caller"]
    # It was told how the first test went.
    assert "It passed 3 of 3 calls on v1: it does not reproduce" in _outputs(prosper_model)[0]


def test_when_it_cannot_reproduce_it_says_so_and_asks_whether_to_go_on(
    client, with_issue, prosper_model
):
    agent_id = with_issue()
    _script(prosper_model, FIX[0], FIX[0], *FIX[1:])

    number = _fix(client, agent_id)["number"]
    pull = _pull(client, agent_id, number)

    assert _types(pull)[-3:] == ["step", "message", "question"]
    assert pull["events"][-2]["text"] == (
        "Could not reproduce it on v1: 3/3. It may be rare or already fixed."
    )
    assert pull["events"][-1]["options"] == ["Yes, propose a fix anyway", "No, leave it as it is"]
    assert pull["prosper"]["state"] == "waiting"
    assert pull["tests"] == []
    # Nothing merges while it waits for the answer.
    assert client.post(f"/api/agents/{agent_id}/pulls/{number}/merge").status_code == 409

    _answer(client, agent_id, number, 0)

    pull = _pull(client, agent_id, number)
    assert _types(pull)[-8:] == [
        "question",
        "answer",
        "step",
        "proposed",
        "rule",
        "checks",
        "proved",
        "message",
    ]
    assert pull["events"][-6]["text"] == "Added the test anyway: 3/3 on v1"
    assert pull["tests"][0]["source"]["before"] == {"version": 1, "passed": 3, "runs": 3}
    assert "They said to go on without a reproduction." in _told(prosper_model)
    # Green, and warned of: nothing shows the change fixes it.
    assert pull["warnings"] == ["Not reproduced on v1: nothing shows this change fixes it."]
    assert client.post(f"/api/agents/{agent_id}/pulls/{number}/merge").status_code == 409
    merged = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge", json={"anyway": True})
    assert merged.status_code == 200
    assert _issue(client, agent_id)["events"][-1]["text"] == "merged without reproducing it on v1"


def test_told_to_stop_it_leaves_the_copy_as_it_is(client, with_issue, prosper_model):
    agent_id = with_issue()
    _script(prosper_model, FIX[0], FIX[0])
    number = _fix(client, agent_id)["number"]

    _answer(client, agent_id, number, 1)

    pull = _pull(client, agent_id, number)
    assert pull["events"][-1]["text"].startswith("Left it as it is: v1 stays unchanged.")
    assert pull["prosper"]["state"] == "done"
    assert (pull["tests"], pull["rules"]) == ([], [])


def test_going_on_without_the_test_it_wrote_says_so_and_stops(client, with_issue, prosper_model):
    agent_id = with_issue()
    _script(prosper_model, FIX[0], FIX[0])
    number = _fix(client, agent_id)["number"]
    store.prosper.update(agent_id, number, candidate=None)  # the record lost it

    _answer(client, agent_id, number, 0)

    pull = _pull(client, agent_id, number)
    assert pull["events"][-1]["text"].startswith("I no longer have the test I wrote")
    assert pull["prosper"]["state"] == "done"
    assert pull["tests"] == []


def test_merging_the_fix_resolves_the_issue_in_the_new_version(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    _script(prosper_model, *FIX)
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


@pytest.mark.parametrize("state", ["ignore", "resolve"])
def test_merging_a_fix_leaves_an_issue_the_person_closed_as_they_left_it(client, with_issue, state):
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


def test_the_same_problem_on_the_fixed_version_opens_the_issue_again(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    _script(prosper_model, *FIX)
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


# ---- a message is the next turn ---------------------------------------------------


def test_a_message_refines_the_fix_and_the_checks_run_again(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    phone = {"step": "Collect details", "text": "If they don't know it, ask for their phone."}
    _script(
        prosper_model,
        *FIX,
        tool("add_rules", rules=[{**phone, "source": None, "quote": None}]),
        tool("run_all", said="Added a rule in Collect details: ask for their phone."),
        {"answer": "Added it; the checks still pass.", "links": []},
    )
    verdicts += [False] * 3
    number = _fix(client, agent_id)["number"]

    client.post(
        f"/api/agents/{agent_id}/pulls/{number}/messages",
        json={"text": "If they don't know it, use their phone number"},
    )
    settle()

    pull = _pull(client, agent_id, number)
    assert _types(pull)[-6:] == ["message", "proposed", "rule", "checks", "proved", "message"]
    assert len(pull["rules"]) == 2
    # The turn knew which issue it fixes, that it is reproduced, and their words.
    facts = _told(prosper_model)
    assert "What it fixes: Issue #2" in facts
    assert '- Reproduced: "Offers only times the clinic is open" passed 0/3 on v1.' not in facts
    assert '- Reproduced: "Offers only open times" passed 0/3 on v1.' in facts
    assert "Their message: If they don't know it, use their phone number" in facts


def test_prosper_ai_takes_a_message_on_any_open_pull_request(client, live_agent, prosper_model):
    agent_id = live_agent()
    number = client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Mine"}).json()["number"]
    _script(
        prosper_model,
        tool("add_rules", rules=[{**RULE, "source": None, "quote": None}]),
        tool("run_all", said="Added a rule in Offer times: only Tuesdays."),
        {"answer": "Done: it offers only Tuesdays now.", "links": []},
    )

    response = client.post(
        f"/api/agents/{agent_id}/pulls/{number}/messages", json={"text": "Only Tuesdays"}
    )
    assert response.status_code == 200
    settle()

    pull = _pull(client, agent_id, number)
    assert [r["text"] for r in pull["rules"]] == [RULE["text"]]
    assert pull["rules"][0]["source"] == {**pull["rules"][0]["source"], "kind": "request"}
    assert pull["prosper"]["state"] == "done"
    # Hand-drawn: no guidelines to read, and its functions keep their names.
    assert "No written guidelines" in _told(prosper_model)
    assert pull["config"] == EXAMPLE | {"name": "Dental Recall"}


# ---- what a fix is held to ------------------------------------------------------


def _edit(agent_id: str, number: int, tool_name: str, **args) -> str:
    return TOOLS[tool_name].edit(Work(agent_id, number, prosper.llm.new_llm()), args)


def test_nothing_changes_before_the_issue_is_reproduced(client, with_issue, prosper_model):
    agent_id = with_issue()
    _script(prosper_model, FIX[0], FIX[0])  # it never fails: the person is asked
    number = _fix(client, agent_id)["number"]

    with pytest.raises(prosper.ToolError, match="Reproduce it first"):
        _edit(agent_id, number, "set_task", step="Greeting", task="Say hi.")
    with pytest.raises(prosper.ToolError, match="Reproduce it first"):
        _edit(agent_id, number, "add_rules", rules=[{**RULE, "source": None, "quote": None}])
    with pytest.raises(prosper.ToolError, match="Reproduce it first"):
        _edit(agent_id, number, "run_all", said="")
    with pytest.raises(prosper.ToolError, match="No tries left"):
        _edit(agent_id, number, "reproduce", **TEST)
    with pytest.raises(prosper.ToolError, match="Only a setup draws the agent whole"):
        _edit(agent_id, number, "draw_agent", agent={})


def test_its_own_test_stays_and_two_steps_change_at_most(
    client, with_issue, prosper_model, verdicts
):
    agent_id = with_issue()
    _script(prosper_model, *FIX)
    verdicts += [False] * 3
    number = _fix(client, agent_id)["number"]
    own = _pull(client, agent_id, number)["tests"][0]

    with pytest.raises(prosper.ToolError, match="That test reproduces what this pull request"):
        _edit(agent_id, number, "rewrite_test", test=own["id"], why="Too strict.", **TEST)
    with pytest.raises(prosper.ToolError, match="That test reproduces what this pull request"):
        _edit(agent_id, number, "remove_test", test=own["id"])
    _edit(agent_id, number, "set_task", step="Greeting", task="Say hi and ask what they need.")
    _edit(agent_id, number, "set_task", step="Offer times", task="Offer Tuesday at 10 AM.")
    with pytest.raises(prosper.ToolError, match="would change 3 steps of v1"):
        _edit(agent_id, number, "set_task", step="Confirm", task="Read it back.")
    with pytest.raises(prosper.ToolError, match="There is no step 'Waitlist'"):
        _edit(agent_id, number, "set_task", step="Waitlist", task="Offer the waitlist.")
    with pytest.raises(prosper.ToolError, match="is 4 sentences"):
        _edit(agent_id, number, "set_task", step="Greeting", task="Hi. Ask. Listen. Go.")


def test_a_restart_mid_fix_is_picked_up_by_the_next_message(
    client, with_issue, prosper_model, verdicts
):
    # Reproduced, and the server stops before the change.
    agent_id = with_issue()
    _script(prosper_model, FIX[0])
    verdicts += [False] * 3
    number = _fix(client, agent_id)["number"]
    store.prosper.set_state(agent_id, number, "working", "Proposing the smallest change")

    store.init_db()  # the server starting again

    pull = _pull(client, agent_id, number)
    assert (pull["prosper"]["state"], _types(pull)[-1]) == ("failed", "interrupted")
    _script(prosper_model, *FIX[1:])
    client.post(f"/api/agents/{agent_id}/pulls/{number}/messages", json={"text": "Go on"})
    settle()

    pull = _pull(client, agent_id, number)
    assert '- Reproduced: "Offers only open times" passed 0/3 on v1.' in _told(prosper_model)
    assert _types(pull)[-5:] == ["proposed", "rule", "checks", "proved", "message"]
    assert pull["warnings"] == []


# ---- A fix that may not fix its issue: warned of, never blocked ---------------------


@pytest.fixture
def fixed_at(client, with_issue, prosper_model, verdicts, monkeypatch):
    """A fix whose own test (id "repro") fails on v1, then scores `after` (one list per run
    of the suite, a rule made plainer between). Returns (agent id, pull)."""
    monkeypatch.setattr(work, "new_id", lambda: "repro")

    def make(*after: list[bool]) -> tuple[str, dict]:
        agent_id = with_issue()
        plainer = {
            "step": "Offer times",
            "text": "Never offer Thursday.",
            "source": None,
            "quote": None,
        }
        rounds = [tool("add_rules", rules=[plainer]), tool("run_all", said="Made it plainer.")]
        _script(prosper_model, *FIX[:3], *rounds * (len(after) - 1), END)
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


def test_a_fix_whose_test_stays_at_two_of_three_warns_and_asks_to_confirm(
    client, fixed_at, prosper_model
):
    agent_id, pull = fixed_at([False, True, True], [False, True, True])
    number = pull["number"]

    # Told after each run that its own test passes only 2 of 3: it took one more round.
    told = [said for said in _outputs(prosper_model) if "passes only 2/3" in said]
    assert len(told) == 2
    assert pull["rules"][-1]["text"] == "Never offer Thursday."
    assert pull["checks"]["state"] == "passed"
    warning = (
        f"The test for Issue #{ISSUE} passes 2 of 3: the problem may still happen in some calls."
    )
    assert pull["warnings"] == [warning]
    listed = client.get(f"/api/agents/{agent_id}/pulls").json()
    assert next(p for p in listed if p["number"] == number)["warnings"] == [warning]

    refused = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge")
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"{warning} Merge anyway to go on."
    merged = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge", json={"anyway": True})
    assert merged.status_code == 200, merged.text

    issue = _issue(client, agent_id)
    assert issue["state"] == "resolved"
    assert issue["events"][-1]["text"] == "merged with its test at 2/3"


def test_one_more_round_can_bring_the_fix_to_three_of_three(client, fixed_at):
    agent_id, pull = fixed_at([False, True, True], [True] * 3)

    assert pull["events"][-2]["type"] == "proved"
    assert pull["events"][-2]["text"].endswith("the new test 0/3 on v1 → 3/3")
    assert pull["warnings"] == []


def test_a_test_already_flaky_on_the_base_is_said_so_and_run_again(
    client, new_agent, prosper_model, fake_checks
):
    """v1 has a test that passed 2 of 3; it fails on the fix: run again, the agent untouched."""
    friendly = {"name": "Sounds friendly", "caller": "You are Ana.", "checks": ["Is friendly"]}
    said = {"Is friendly": [False, True, True, False, False, True, True, True, True]}

    async def judge(check, transcript):
        verdict = said[check].pop(0) if said.get(check) else True
        return {"pass": verdict, "detail": "Judged.", "tokens": {"prompt": 1, "completion": 1}}

    fake_checks.judge = judge
    agent_id, _ = new_agent()
    client.post(f"/api/agents/{agent_id}/pulls/1/tests", json=friendly)
    settle()
    assert client.post(f"/api/agents/{agent_id}/pulls/1/merge").status_code == 200
    prosper_model.script = {
        "callers": [CALLERS],
        "audit": [copy.deepcopy(REVIEW), copy.deepcopy(REVIEW)],
        "grouping": [{"placements": [{"finding": 0, "issue": ISSUE}]}],
    }
    client.post(f"/api/agents/{agent_id}/calls/play")
    settle()
    said["Offers only times the clinic is open"] = [False] * 3  # reproduced; then it passes
    _script(prosper_model, *FIX[:3], tool("run_one", test="Sounds friendly"), END)

    number = _fix(client, agent_id)["number"]
    pull = _pull(client, agent_id, number)

    ran = _outputs(prosper_model)[2]
    assert "Sounds friendly · failing, 1/3 · already flaky on v1 (2/3 there)" in ran
    assert "Already flaky (2/3) on v1: Sounds friendly." in _told(prosper_model)
    assert [r["text"] for r in pull["rules"]] == [RULE["text"]]  # only the fix's
    assert pull["checks"]["state"] == "passed"
    assert _types(pull)[-2:] == ["proved", "message"]
