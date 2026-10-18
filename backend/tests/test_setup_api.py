#
# Building an agent with Prosper AI, through the API: the guidelines go in,
# PR #1 fills in with the agent, its rules and tests, a question waits for its
# answer, the suite runs, and the agent can go live. Prosper AI's model is
# scripted and the simulated calls run on fakes: nothing here reaches OpenAI.
#

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
        {"name": "Asks for advice", "caller": "Peter asks.", "checks": ["Never gives advice"]},
    ]
}
QUESTION = {
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
            "rules": [RULES],
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


def test_prosper_ai_builds_pr_1_and_asks_what_the_guidelines_leave_open(client, scripted):
    scripted()

    agent_id, pull = _create(client)

    assert pull["title"] == "Set up Riverside"
    assert pull["prosper"]["state"] == "waiting"
    assert _types(pull) == ["request", "opened", "step", "step", "step", "step", "question"]
    request, opened, read, drew, rules, tests, question = pull["events"]
    assert (request["by"], request["notes"]) == ("you", NOTES)
    assert request["files"] == [{"name": "hours.txt", "kind": "TXT", "pages": None}]
    assert opened["by"] == "Prosper AI"
    assert [e["text"] for e in (read, drew, rules, tests)] == [
        "Read 1 file and your notes",
        "Drew 3 steps",
        "Wrote 2 rules, each linked to its line",
        "Wrote 2 tests",
    ]
    assert (question["text"], question["options"]) == (
        QUESTION["text"],
        ["Offer the waitlist", "Ask them to call back"],
    )
    assert [node["name"] for node in pull["config"]["nodes"]] == [
        "greeting",
        "collect_details",
        "confirm",
    ]
    assert pull["rules"][1]["step"] == "collect_details"
    assert pull["rules"][1]["source"] == {
        "kind": "guidelines",
        "pull": 1,
        "file": "hours.txt",
        "quote": "Tuesday 10 AM and Thursday 2 PM",
    }
    assert [test["name"] for test in pull["tests"]] == ["Books", "Asks for advice"]
    # The suite waits for the answer, which changes the agent.
    assert pull["checks"] is None


def test_it_cannot_merge_until_answered_then_the_suite_runs(client, scripted):
    scripted()
    agent_id, pull = _create(client)

    refused = client.post(f"/api/agents/{agent_id}/pulls/1/merge")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Prosper AI needs your answer in PR #1 first."

    question = pull["events"][-1]["question"]
    answered = client.post(
        f"/api/agents/{agent_id}/pulls/1/answers", json={"question": question, "option": 0}
    )
    assert answered.status_code == 200
    rule = answered.json()["rules"][-1]
    assert (rule["step"], rule["text"]) == ("collect_details", "Offer the waitlist.")
    assert rule["source"] == {
        "kind": "answer",
        "pull": 1,
        "file": None,
        "quote": "Offer the waitlist",
    }
    checks.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert _types(pull)[-3:] == ["answer", "rule", "checks"]
    assert pull["prosper"]["state"] == "done"
    assert pull["checks"]["state"] == "passed"
    merged = client.post(f"/api/agents/{agent_id}/pulls/1/merge")
    assert merged.status_code == 200
    assert merged.json()["merged_version"] == 1


def test_an_answer_in_its_own_words_goes_through_prosper_ai(client, scripted):
    reply = {
        "reply": "Added a rule to Collect details.",
        "agent": DRAFT,
        "rules": [{"step": "Collect details", "text": "Offer the waitlist if no time works."}],
        "tests": [],
    }
    model = scripted(change=[reply])
    agent_id, _ = _create(client)

    response = client.post(
        f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Put them on the waitlist"}
    )
    assert response.json()["prosper"]["state"] == "working"
    setup.wait()
    checks.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert _types(pull)[-4:] == ["answer", "message", "rule", "checks"]
    assert pull["rules"][-1]["source"]["kind"] == "answer"
    assert pull["rules"][-1]["source"]["quote"] == "Put them on the waitlist"
    (asked,) = model.asked["change"]
    assert 'Their answer: "Put them on the waitlist"' in asked[-1]["content"]


def test_a_request_in_the_conversation_changes_pr_1(client, scripted):
    shorter = {**DRAFT, "nodes": [{**DRAFT["nodes"][0], "task": "Say hi."}, *DRAFT["nodes"][1:]]}
    reply = {
        "reply": "Shortened the greeting.",
        "agent": shorter,
        "rules": [],
        "tests": [{"name": "Short hello", "caller": "Ana.", "checks": ["Reaches Greeting"]}],
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
    assert pull["checks"]["total"] == 3


def test_a_drafted_agent_the_builder_refuses_is_drawn_again_with_the_error(client, scripted):
    model = scripted(agent=({**DRAFT, "initial_node": "start"}, DRAFT))

    _, pull = _create(client)

    assert len(pull["config"]["nodes"]) == 3
    assert "initial_node 'start' is not a defined node" in model.asked["agent"][1][-1]["content"]


def test_when_it_cannot_finish_it_says_so_and_a_message_tries_again(client, scripted):
    scripted(agent=[{**DRAFT, "initial_node": "start"}] * 3 + [DRAFT])

    agent_id, pull = _create(client)

    assert pull["prosper"]["state"] == "failed"
    assert pull["events"][-1]["by"] == "Prosper AI"
    assert pull["events"][-1]["text"].startswith("I couldn't finish: initial_node 'start'")
    assert pull["config"]["nodes"] == []

    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Try again"})
    setup.wait()

    pull = client.get(f"/api/agents/{agent_id}/pulls/1").json()
    assert len(pull["config"]["nodes"]) == 3
    assert pull["prosper"]["state"] == "waiting"


def test_your_own_changes_wait_while_prosper_ai_works(client, scripted, agent):
    scripted()
    agent_id, _ = _create(client)
    store.prosper.set_state(agent_id, 1, "working", "Drawing the steps")

    saved = client.put(f"/api/agents/{agent_id}/pulls/1", json={"config": agent})
    talked = client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Hello"})

    assert saved.status_code == 409
    assert saved.json()["detail"] == "Prosper AI is still working on PR #1."
    assert talked.status_code == 409


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
