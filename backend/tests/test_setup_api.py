#
# Building an agent with Prosper AI, through the API: the guidelines go in,
# Prosper AI asks what they leave open, then with the answers PR #1 fills in
# with the agent, its rules and its tests, the suite runs, and the agent can
# go live. Prosper AI's model is
# scripted and the simulated calls run on fakes: nothing here reaches OpenAI.
#

import json

import pytest

import store
from api import checks
from copilot import setup
from tests.fakes import call, say
from tests.test_copilot import DRAFT

NOTES = "Never give medical advice over the phone."
HOURS = b"New bookings: Tuesday 10 AM and Thursday 2 PM."

RULES = {
    "rules": [
        {
            "step": None,
            "text": "Never give medical advice.",
            "source": "your notes",
            "quote": NOTES,
        },
        {
            "step": "Collect details",
            "text": "Only offer Tuesday 10 AM or Thursday 2 PM.",
            "source": "hours.txt",
            "quote": "Tuesday 10 AM and Thursday 2 PM",
        },
    ]
}
TESTS = {
    "tests": [
        {"name": "Books", "caller": "Maria books.", "checks": ["Reaches Confirm", "Ends the call"]},
        {
            "name": "Asks for advice",
            "caller": "Peter.",
            "checks": ["Never gives advice", "Ends the call"],
        },
        *(
            {
                "name": f"Books {n}",
                "caller": "Ana books.",
                "checks": ["Reaches Confirm", "Ends the call"],
            }
            for n in (2, 3, 4)
        ),
    ]
}
# Asked before anything is drawn: options are what the clinic picks.
QUESTION = {
    "text": "What should the agent do when no time works?",
    "options": ["Offer the waitlist", "Ask them to call back"],
}
# Asked by the self-check, on a drawn agent: each option carries its rule.
GAP = {
    "text": "What should the agent do when no time works?",
    "options": [
        {
            "label": "Offer the waitlist",
            "rule": {"step": "Collect details", "text": "Offer the waitlist."},
        },
        {
            "label": "Ask them to call back",
            "rule": {"step": None, "text": "Ask them to call back."},
        },
    ],
}


def answered(quote: str = "Offer the waitlist") -> dict:
    """The rules, with the one the clinic's answer becomes."""
    rule = {"step": "Collect details", "text": "Offer the waitlist if no time works."}
    return {"rules": [*RULES["rules"], {**rule, "source": "your answer", "quote": quote}]}


# A call through the drafted agent, from greeting to goodbye.
CALL = [
    say("Hi, Riverside clinic. How can I help?"),
    call("go_to_collect_details", intent="book"),
    say("Your full name, please?"),
    call("go_to_confirm", full_name="Maria Lopez"),
    say("Booked. Goodbye!"),
]


@pytest.fixture
def scripted(prosper_model, fake_checks):
    """Script Prosper AI's answers; the suite's calls follow the drafted agent."""
    fake_checks.script = CALL
    fake_checks.lines = ["I'd like to book.", "Maria Lopez."]

    def script(questions=(QUESTION,), agent=(DRAFT,), **more):
        prosper_model.script = {
            "agent": list(agent),
            "rules": [answered() if questions else RULES],
            "tests": [TESTS],
            "questions": [{"questions": list(questions)}],
            **{name: list(answers) for name, answers in more.items()},
        }
        return prosper_model

    return script


def _create(client, notes=NOTES, files=(("hours.txt", HOURS),)) -> tuple[str, dict]:
    response = client.post(
        "/api/agents/from-guidelines",
        data={"name": "Riverside", "guidelines": notes},
        files=[("files", (name, data, "text/plain")) for name, data in files],
    )
    assert response.status_code == 201, response.json()
    setup.wait()
    created = response.json()
    agent_id = created["agent"]["id"]
    return agent_id, client.get(f"/api/agents/{agent_id}/pulls/1").json()


def _types(pull: dict) -> list[str]:
    return [event["type"] for event in pull["events"]]


def _pick(client, agent_id: str, pull: dict, option: int = 0) -> dict:
    question = next(e for e in reversed(pull["events"]) if e["type"] == "question")
    response = client.post(
        f"/api/agents/{agent_id}/pulls/1/answers",
        json={"question": question["question"], "option": option},
    )
    assert response.status_code == 200, response.json()
    setup.wait()
    return client.get(f"/api/agents/{agent_id}/pulls/1").json()


def test_prosper_ai_asks_what_the_guidelines_leave_open_before_drawing(client, scripted):
    model = scripted()

    agent_id, pull = _create(client)

    assert pull["title"] == "Set up Riverside"
    assert pull["prosper"]["state"] == "waiting"
    assert pull["config"]["nodes"] == []  # nothing drawn yet
    assert _types(pull) == ["request", "opened", "step", "message", "question"]
    request, opened, read, said, question = pull["events"]
    assert (request["by"], request["notes"]) == ("you", NOTES)
    assert request["files"] == [{"name": "hours.txt", "kind": "TXT", "pages": None}]
    assert opened["by"] == "Prosper AI"
    assert read["text"] == "Read 1 file and your notes"
    assert said["text"] == "I need your answers before I draw Riverside."
    assert (question["text"], question["options"]) == (QUESTION["text"], QUESTION["options"])
    assert "agent" not in model.asked and "tests" not in model.asked
    refused = client.post(f"/api/agents/{agent_id}/pulls/1/merge")
    assert refused.json()["detail"] == "Prosper AI needs your answer in PR #1 first."


def test_with_the_answers_it_draws_writes_rules_then_tests_and_runs_them(client, scripted):
    model = scripted()
    agent_id, pull = _create(client)

    pull = _pick(client, agent_id, pull)
    checks.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert _types(pull)[-5:] == ["answer", "step", "step", "step", "checks"]
    assert [e["text"] for e in pull["events"][-4:-1]] == [
        "Drew 3 steps",
        "Wrote 3 rules, each linked to its line or your answer",
        "Wrote 5 tests",
    ]
    assert [node["name"] for node in pull["config"]["nodes"]] == [
        "greeting",
        "collect_details",
        "confirm",
    ]
    # The answer is in what drew the agent, and became a rule on its step.
    assert (
        '"What should the agent do when no time works?" → "Offer the waitlist"'
        in (model.asked["agent"][0][-1]["content"])
    )
    rule = pull["rules"][-1]
    assert rule["step"] == "collect_details"
    assert rule["source"] == {
        "kind": "answer",
        "pull": 1,
        "file": None,
        "quote": "Offer the waitlist",
    }
    assert pull["rules"][1]["source"] == {
        "kind": "guidelines",
        "pull": 1,
        "file": "hours.txt",
        "quote": "Tuesday 10 AM and Thursday 2 PM",
    }
    # Tests last, knowing the rules the answer became.
    assert "Offer the waitlist if no time works." in model.asked["tests"][0][-1]["content"]
    assert pull["prosper"]["state"] == "done"
    assert pull["checks"]["state"] == "passed"
    merged = client.post(f"/api/agents/{agent_id}/pulls/1/merge")
    assert merged.status_code == 200
    assert merged.json()["merged_version"] == 1


def test_an_answer_must_become_a_rule_quoting_it(client, scripted):
    model = scripted(rules=[RULES, answered()])
    agent_id, pull = _create(client)

    _pick(client, agent_id, pull)

    refused = model.asked["rules"][1][-1]["content"]
    assert "The clinic answered 'Offer the waitlist': write it as a rule" in refused


def test_an_answer_in_its_own_words_is_kept_for_the_drawing(client, scripted):
    model = scripted(rules=[answered("The waitlist, always")])
    agent_id, _ = _create(client)

    response = client.post(
        f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "The waitlist, always"}
    )
    assert response.json()["prosper"]["state"] == "working"
    setup.wait()
    checks.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert pull["rules"][-1]["source"]["quote"] == "The waitlist, always"
    assert '→ "The waitlist, always"' in model.asked["agent"][0][-1]["content"]
    assert "change" not in model.asked
    assert pull["checks"]["state"] == "passed"


def test_with_no_gap_it_says_so_and_goes_straight_on(client, scripted):
    scripted(questions=())

    agent_id, pull = _create(client)

    assert (
        pull["events"][3]["text"]
        == "Found no gaps in the guidelines that change how Riverside behaves"
    )
    assert len(pull["config"]["nodes"]) == 3 and len(pull["tests"]) == 5


def test_a_request_in_the_conversation_changes_pr_1(client, scripted):
    shorter = {**DRAFT, "nodes": [{**DRAFT["nodes"][0], "task": "Say hi."}, *DRAFT["nodes"][1:]]}
    reply = {
        "reply": "Shortened the greeting.",
        "agent": shorter,
        "rules": [],
        "tests": [
            {
                "name": "Short hello",
                "caller": "Ana.",
                "checks": ["Reaches Greeting", "Ends the call"],
            }
        ],
        "remove": [],
    }
    scripted(questions=(), change=[reply])
    agent_id, pull = _create(client)
    checks.wait()
    assert client.get(f"/api/agents/{agent_id}/pulls/1").json()["checks"]["state"] == "passed"

    client.post(
        f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Make the greeting shorter"}
    )
    setup.wait()
    checks.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    message = [e for e in pull["events"] if e["type"] == "message"][-1]
    assert (message["by"], message["text"], message["changed"]) == (
        "Prosper AI",
        "Shortened the greeting.",
        True,
    )
    assert pull["config"]["nodes"][0]["task_messages"][0]["content"] == "Say hi."
    assert pull["tests"][-1]["source"] == {
        "kind": "request",
        "pull": 1,
        "file": None,
        "quote": "Make the greeting shorter",
    }
    assert pull["checks"]["total"] == 6


def test_a_change_can_take_out_what_this_pull_request_added(client, scripted):
    reply = {"reply": "Moved the rule.", "agent": DRAFT, "rules": [], "tests": [], "remove": []}
    model = scripted(questions=(), change=[{**reply, "remove": ["nope"]}, reply])
    agent_id, pull = _create(client)
    checks.wait()
    rule = pull["rules"][0]
    model.script["change"][1]["remove"] = [rule["id"]]

    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Drop that rule"})
    setup.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert rule["id"] not in [r["id"] for r in pull["rules"]]
    taken = next(e for e in pull["events"] if e["type"] == "rule" and e.get("removed"))
    assert (taken["by"], taken["text"]) == ("Prosper AI", rule["text"])
    refused = model.asked["change"][1][-1]["content"]
    assert "'nope' is not the id of a rule or test that can be taken out" in refused


def test_a_drafted_agent_the_builder_refuses_is_drawn_again_with_the_error(client, scripted):
    model = scripted(questions=(), agent=({**DRAFT, "initial_node": "start"}, DRAFT))

    _, pull = _create(client)

    assert len(pull["config"]["nodes"]) == 3
    assert "initial_node 'start' is not a defined node" in model.asked["agent"][1][-1]["content"]


def test_when_it_cannot_finish_it_says_so_and_a_message_tries_again(client, scripted):
    scripted(questions=(), agent=[{**DRAFT, "initial_node": "start"}] * 3 + [DRAFT])

    agent_id, pull = _create(client)

    assert pull["prosper"]["state"] == "failed"
    assert pull["events"][-1]["by"] == "Prosper AI"
    assert pull["events"][-1]["text"].startswith("I couldn't finish: initial_node 'start'")
    assert pull["config"]["nodes"] == []

    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Try again"})
    setup.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert len(pull["config"]["nodes"]) == 3
    assert pull["prosper"]["state"] == "done"


def test_your_own_changes_wait_while_prosper_ai_works(client, scripted, agent):
    scripted()
    agent_id, _ = _create(client)
    store.prosper.set_state(agent_id, 1, "working", "Drawing the steps")

    saved = client.put(f"/api/agents/{agent_id}/pulls/1", json={"config": agent})
    talked = client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Hello"})
    question = client.get(f"/api/agents/{agent_id}/pulls/1").json()["events"][-1]["question"]
    picked = client.post(
        f"/api/agents/{agent_id}/pulls/1/answers", json={"question": question, "option": 0}
    )

    assert saved.status_code == 409
    assert saved.json()["detail"] == "Prosper AI is still working on PR #1."
    assert talked.status_code == 409
    assert picked.status_code == 409


@pytest.mark.parametrize(
    "notes, files, problem",
    [
        ("  ", (), "Paste the guidelines or attach a file"),
        ("", (("photo.png", b"..."),), "'photo.png' is not a PDF, a Word document or a text file."),
        ("", (("empty.txt", b"  \n "),), "'empty.txt' has no text to read."),
    ],
)
def test_guidelines_it_cannot_read_are_refused_before_anything_is_created(
    client, notes, files, problem
):
    response = client.post(
        "/api/agents/from-guidelines",
        data={"name": "Riverside", "guidelines": notes},
        files=[("files", (name, data, "text/plain")) for name, data in files] or None,
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith(problem)
    assert len(client.get("/api/agents").json()) == 1  # the sample only


def test_prosper_ai_only_talks_in_the_pull_request_it_set_up(client, new_agent):
    agent_id, _ = new_agent()

    response = client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Hi"})

    assert response.status_code == 409


def test_a_change_is_asked_with_what_failed_last_time(client, scripted, fake_checks, monkeypatch):
    monkeypatch.setattr(setup, "MAX_ROUNDS", 0)  # no review of its own first
    reply = {"reply": "Fixed.", "agent": DRAFT, "rules": [], "tests": [], "remove": []}
    model = scripted(questions=(), change=[reply])
    fake_checks.verdict = False  # "Never gives advice" is judged, and fails
    agent_id, _ = _create(client)
    checks.wait()

    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Make it pass"})
    setup.wait()

    (asked,) = model.asked["change"]
    assert (
        "What failed when its tests last ran:\n- Asks for advice: failed 3 of 3"
        in asked[-1]["content"]
    )


def test_work_a_restart_interrupted_can_be_retried(client, scripted, agent):
    scripted()
    agent_id, _ = _create(client)
    store.prosper.set_state(agent_id, 1, "working", "Writing rules and tests")

    store.init_db()  # the server starting again

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert pull["prosper"]["state"] == "failed"
    assert (pull["events"][-1]["type"], pull["events"][-1]["by"]) == ("interrupted", "Prosper AI")
    assert (
        client.put(f"/api/agents/{agent_id}/pulls/1", json={"config": agent}).status_code
        == 200
    )


def test_a_retry_finishes_the_setup_from_the_step_that_failed(client, scripted):
    # Drawn and given rules, then every request for its tests is refused.
    bad = {"tests": [{"name": "X", "caller": "Y", "checks": ["Reaches Waitlist"]}]}
    model = scripted(tests=[bad] * 3 + [TESTS])
    agent_id, pull = _create(client)
    pull = _pick(client, agent_id, pull)
    assert pull["prosper"]["state"] == "failed"
    assert len(pull["config"]["nodes"]) == 3 and pull["tests"] == []

    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Try again"})
    setup.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert [t["name"] for t in pull["tests"]][:2] == ["Books", "Asks for advice"]
    assert len(model.asked["agent"]) == 1  # not drawn again
    assert len(model.asked["rules"]) == 1 and len(model.asked["questions"]) == 1
    # The answer given before the failure is still the one the rules quote.
    assert pull["rules"][-1]["source"]["quote"] == "Offer the waitlist"
    assert pull["prosper"]["state"] == "done"


# ---- Prosper AI checking its own draft ----------------------------------------


def _review(verdict: str, **more) -> dict:
    """A review of the one failing test, "Asks for advice" (its judged check fails)."""
    return {
        "summary": more.pop("summary", "Checked the failing test."),
        "verdicts": [{"test": "ADVICE", "verdict": verdict, "why": more.pop("why", "Because.")}],
        "agent": more.pop("agent", DRAFT),
        "rules": [],
        "remove_rules": [],
        "tests": [],
        "questions": [],
        **more,
    }


def _with_ids(model, review: dict, pull: dict) -> dict:
    """`review` with the failing test's real id in place of ADVICE."""
    advice = next(t["id"] for t in pull["tests"] if t["name"] == "Asks for advice")
    text = json.dumps(review).replace("ADVICE", advice)
    return json.loads(text)


def _set_up_failing(client, scripted, fake_checks, reviews):
    """A setup with no questions whose judged check fails; Prosper AI reviews with `reviews`."""
    model = scripted(questions=())
    fake_checks.verdict = False
    model.script["review"] = []
    agent_id, pull = _create(client)
    model.script["review"] = [_with_ids(model, review, pull) for review in reviews]
    checks.wait()
    from tests.conftest import settle

    settle()
    return agent_id, model


def test_when_the_agent_is_wrong_prosper_ai_changes_the_agent(client, scripted, fake_checks):
    stricter = {**DRAFT, "persona": DRAFT["persona"] + " Never advise on medicine."}
    review = _review("agent", agent=stricter, why="Its persona never said no advice.")
    agent_id, model = _set_up_failing(client, scripted, fake_checks, [review, review])

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert pull["config"]["persona"].endswith("Never advise on medicine.")
    said = next(e for e in pull["events"] if e["type"] == "message" and e.get("details"))
    assert said["changed"] is True
    assert said["details"] == [
        "Asks for advice · the agent was wrong: Its persona never said no advice."
    ]
    assert "failed 3 of 3" in model.asked["review"][0][-1]["content"]


def test_a_test_asking_for_more_than_the_guidelines_is_rewritten(client, scripted, fake_checks):
    rewrite = {"id": "ADVICE", "name": "Asks for advice", "caller": "Peter."}
    rewrite["checks"] = ["Reaches Confirm", "Ends the call"]
    review = _review("test", tests=[rewrite], why="No guideline says that.")
    agent_id, model = _set_up_failing(client, scripted, fake_checks, [review])

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    advice = next(t for t in pull["tests"] if t["name"] == "Asks for advice")
    assert advice["checks"] == ["Reaches Confirm", "Ends the call"]
    assert advice["source"]["kind"] == "guidelines"  # the same test, rewritten
    rewritten = next(e for e in pull["events"] if e.get("rewritten"))
    assert (rewritten["by"], rewritten["why"]) == ("Prosper AI", "No guideline says that.")
    assert pull["checks"]["state"] == "passed"
    assert len(model.asked["review"]) == 1


def test_a_gap_the_failure_shows_becomes_a_question(client, scripted, fake_checks):
    review = _review("gap", questions=[GAP])
    agent_id, _ = _set_up_failing(client, scripted, fake_checks, [review])

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert pull["prosper"]["state"] == "waiting"
    assert pull["events"][-1]["type"] == "question"


def test_it_checks_its_own_work_twice_at_most_then_says_what_fails(client, scripted, fake_checks):
    stricter = {**DRAFT, "persona": "Never advise."}
    again = {**DRAFT, "persona": "Never, ever advise."}
    reviews = [_review("agent", agent=stricter), _review("agent", agent=again)]
    agent_id, model = _set_up_failing(client, scripted, fake_checks, reviews)

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert len(model.asked["review"]) == 2
    last = pull["events"][-1]
    assert last["by"] == "Prosper AI"
    assert last["text"].startswith("Still failing after 2 rounds of checking my own work")
    assert pull["prosper"]["state"] == "done"


def test_a_review_gives_every_failing_test_a_verdict_and_does_what_it_says():
    from copilot import artifacts

    before = artifacts.to_config("Riverside", DRAFT)
    failing = {"t1": "Asks for advice"}
    review = json.loads(json.dumps(_review("agent")).replace("ADVICE", "t1"))

    with pytest.raises(ValueError, match="Give a verdict for every failing test"):
        artifacts.check_review({**review, "verdicts": []}, failing, before, set())
    with pytest.raises(ValueError, match="nothing in the agent changed"):
        artifacts.check_review(review, failing, before, set())
    with pytest.raises(ValueError, match="Rewrite exactly the tests whose verdict is 'test'"):
        artifacts.check_review(
            {**review, "verdicts": [{**review["verdicts"][0], "verdict": "test"}]},
            failing,
            before,
            set(),
        )
