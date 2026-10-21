#
# Building an agent with Prosper AI, through the API: the guidelines go in,
# Prosper AI asks what they leave open, then with the answers it draws the
# agent in PR #1, writes its rules and tests with its tools, runs them, and
# the agent can go live. The guards of a setup are its tools': nothing drawn
# before every answer is in, no test taken out, every answer a rule.
#
# Prosper AI's model is scripted (each answer a tool call or its last word)
# and the simulated calls run on fakes: nothing here reaches OpenAI.
#

import pytest

import store
from api import checks
from api.tools import TOOLS
from copilot import agent as prosper
from copilot.agent import Work
from tests.conftest import settle
from tests.fakes import call, say, tool
from tests.test_copilot import DRAFT

NOTES = "Never give medical advice over the phone."
HOURS = b"New bookings: Tuesday 10 AM and Thursday 2 PM."

RULES = [
    {"step": None, "text": "Never give medical advice.", "source": "your notes", "quote": NOTES},
    {
        "step": "Collect details",
        "text": "Only offer Tuesday 10 AM or Thursday 2 PM.",
        "source": "hours.txt",
        "quote": "Tuesday 10 AM and Thursday 2 PM",
    },
]
WAITLIST = {
    "step": "Collect details",
    "text": "Offer the waitlist if no time works.",
    "source": "your answer",
    "quote": "Offer the waitlist",
}
TESTS = [
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
QUESTION = {
    "text": "What should the agent do when no time works?",
    "options": [
        {"label": "Offer the waitlist", "rule": None},
        {"label": "Ask them to call back", "rule": None},
    ],
}
ASK = tool("ask", said="I need your answers before I draw Riverside.", questions=[QUESTION])
DONE = {"answer": "All 5 tests pass: merge PR #1 to put it live.", "links": []}
# With the answers: the agent, its rules, its tests, a run, and its last word.
BUILD = [
    tool("draw_agent", agent=DRAFT),
    tool("add_rules", rules=[*RULES, WAITLIST]),
    tool("add_tests", tests=TESTS),
    tool("run_all", said=""),
    DONE,
]

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
    """Script Prosper AI's turns; the suite's calls follow the drafted agent."""
    fake_checks.script = CALL
    fake_checks.lines = ["I'd like to book.", "Maria Lopez."]

    def script(*turns):
        prosper_model.script = {"work": [step for turn in turns for step in turn]}
        return prosper_model

    return script


def _create(client, notes=NOTES, files=(("hours.txt", HOURS),)) -> tuple[str, dict]:
    response = client.post(
        "/api/agents/from-guidelines",
        data={"name": "Riverside", "guidelines": notes},
        files=[("files", (name, data, "text/plain")) for name, data in files],
    )
    assert response.status_code == 201, response.json()
    settle()
    agent_id = response.json()["agent"]["id"]
    return agent_id, _pull(client, agent_id)


def _pull(client, agent_id: str) -> dict:
    return client.get(f"/api/agents/{agent_id}/pulls/1").json()


def _types(pull: dict) -> list[str]:
    return [event["type"] for event in pull["events"]]


def _pick(client, agent_id: str, pull: dict, option: int = 0) -> dict:
    question = next(e for e in reversed(pull["events"]) if e["type"] == "question")
    response = client.post(
        f"/api/agents/{agent_id}/pulls/1/answers",
        json={"question": question["question"], "option": option},
    )
    assert response.status_code == 200, response.json()
    settle()
    return _pull(client, agent_id)


def _outputs(model) -> list[str]:
    """What each tool told the model, in order."""
    return [asked[-1]["output"] for asked in model.asked["work"] if "output" in asked[-1]]


def _told(model, turn: int = -1) -> str:
    """What a turn of the work started from: the facts, its first message."""
    starts = [asked for asked in model.asked["work"] if len(asked) == 2]
    return starts[turn][1]["content"]


def test_prosper_ai_asks_what_the_guidelines_leave_open_before_drawing(client, scripted):
    model = scripted([ASK])

    agent_id, pull = _create(client)

    assert pull["title"] == "Set up Riverside"
    assert pull["prosper"]["state"] == "waiting"
    assert pull["config"]["nodes"] == []  # nothing drawn yet
    assert _types(pull) == ["request", "opened", "step", "message", "question"]
    request, opened, read, said, question = pull["events"]
    assert (request["by"], request["notes"]) == ("you", NOTES)
    assert opened["by"] == "Prosper AI"
    assert read["text"] == "Read 1 file and your notes"
    assert said["text"] == "I need your answers before I draw Riverside."
    assert question["options"] == ["Offer the waitlist", "Ask them to call back"]
    # It worked from the guidelines, with the setup's brief.
    facts = _told(model)
    assert "=== hours.txt ===\nNew bookings: Tuesday 10 AM" in facts
    assert "You have not asked the clinic about the guidelines' gaps yet." in facts
    refused = client.post(f"/api/agents/{agent_id}/pulls/1/merge")
    assert refused.json()["detail"] == "Prosper AI needs your answer in PR #1 first."


def test_with_the_answers_it_draws_writes_rules_then_tests_and_runs_them(client, scripted):
    model = scripted([ASK], BUILD)
    agent_id, pull = _create(client)

    pull = _pick(client, agent_id, pull)

    assert _types(pull)[-6:] == ["answer", "step", "step", "step", "checks", "message"]
    assert [e["text"] for e in pull["events"][-5:-2]] == [
        "Drew 3 steps",
        "Wrote 3 rules, each linked to its line or your answer",
        "Wrote 5 tests",
    ]
    assert pull["events"][-1]["text"] == DONE["answer"]
    assert [node["name"] for node in pull["config"]["nodes"]] == [
        "greeting",
        "collect_details",
        "confirm",
    ]
    # The answer started the turn, and became a rule on its step, quoting it.
    assert '"What should the agent do when no time works?" → "Offer the waitlist"' in _told(model)
    rule = pull["rules"][-1]
    assert (rule["step"], rule["source"]["kind"], rule["source"]["quote"]) == (
        "collect_details",
        "answer",
        "Offer the waitlist",
    )
    assert pull["rules"][1]["source"] == {
        "kind": "guidelines",
        "pull": 1,
        "file": "hours.txt",
        "quote": "Tuesday 10 AM and Thursday 2 PM",
    }
    assert pull["prosper"]["state"] == "done"
    assert pull["prosper"]["usage"]["requests"] > 0  # what it spent, counted
    assert pull["checks"]["state"] == "passed"
    # The run's results went back to it before its last word.
    told = model.asked["work"][-1][-1]["output"]
    assert "The tests of PR #1, 3 calls each: 5 of 5 pass." in told
    merged = client.post(f"/api/agents/{agent_id}/pulls/1/merge")
    assert merged.status_code == 200
    assert merged.json()["merged_version"] == 1


def test_an_answer_in_its_own_words_starts_the_drawing(client, scripted):
    own = {**WAITLIST, "quote": "The waitlist, always"}
    model = scripted([ASK], [BUILD[0], tool("add_rules", rules=[*RULES, own]), *BUILD[2:]])
    agent_id, _ = _create(client)

    response = client.post(
        f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "The waitlist, always"}
    )
    assert response.json()["prosper"]["state"] == "working"
    settle()

    pull = _pull(client, agent_id)
    assert pull["rules"][-1]["source"]["quote"] == "The waitlist, always"
    assert '→ "The waitlist, always"' in _told(model)
    assert pull["checks"]["state"] == "passed"


def test_with_no_gap_it_says_so_and_goes_straight_on(client, scripted):
    scripted(
        [tool("ask", said="", questions=[]), BUILD[0], tool("add_rules", rules=RULES), *BUILD[2:]]
    )

    agent_id, pull = _create(client)

    assert pull["events"][3]["text"] == (
        "Found no gaps in the guidelines that change how Riverside behaves"
    )
    assert len(pull["config"]["nodes"]) == 3 and len(pull["tests"]) == 5
    assert pull["checks"]["state"] == "passed"


def test_a_refused_edit_goes_back_to_the_model_which_corrects_it(client, scripted):
    # It tries to draw before asking: refused, it asks.
    model = scripted([tool("draw_agent", agent=DRAFT), ASK])

    agent_id, pull = _create(client)

    assert pull["config"]["nodes"] == []
    refused = model.asked["work"][1][-1]["output"]
    assert refused.startswith("Refused: Ask the clinic what the guidelines leave open first")
    assert pull["prosper"]["state"] == "waiting"


def test_every_answer_becomes_a_rule_before_the_tests_run(client, scripted):
    # Its rules leave the answer out: the run is refused until one quotes it.
    model = scripted(
        [ASK],
        [
            BUILD[0],
            tool("add_rules", rules=RULES),
            BUILD[2],
            tool("run_all", said=""),
            tool("add_rules", rules=[WAITLIST]),
            *BUILD[3:],
        ],
    )
    agent_id, pull = _create(client)

    pull = _pick(client, agent_id, pull)

    [refused] = [said for said in _outputs(model) if said.startswith("Refused")]
    assert refused.startswith('Refused: The clinic answered "Offer the waitlist": make it a rule')
    assert pull["checks"]["state"] == "passed"


def _work(agent_id: str, number: int = 1) -> Work:
    return Work(agent_id, number, prosper.llm.new_llm())


def _edit(agent_id: str, tool_name: str, number: int = 1, **args) -> str:
    return TOOLS[tool_name].edit(_work(agent_id, number), args)


def test_a_setup_draws_nothing_until_every_question_has_its_answer(client, scripted):
    scripted([ASK])
    agent_id, _ = _create(client)

    with pytest.raises(prosper.ToolError, match="has not answered every question"):
        _edit(agent_id, "draw_agent", agent=DRAFT)
    with pytest.raises(prosper.ToolError, match="Only a fix or a change reproduces"):
        _edit(agent_id, "reproduce", **TESTS[0])


def test_a_setup_never_takes_a_test_out_and_writes_seven_at_most(client, scripted):
    scripted([ASK], BUILD)
    agent_id, pull = _create(client)
    pull = _pick(client, agent_id, pull)

    with pytest.raises(prosper.ToolError, match="A setup never takes a test out"):
        _edit(agent_id, "remove_test", test=pull["tests"][0]["id"])
    with pytest.raises(prosper.ToolError, match="A setup writes 7 tests at most"):
        _edit(agent_id, "add_tests", tests=TESTS)
    with pytest.raises(prosper.ToolError, match="is not in 'your notes' word for word"):
        _edit(agent_id, "add_rules", rules=[{**RULES[0], "quote": "Always advise."}])
    with pytest.raises(prosper.ToolError, match="needs its source"):
        _edit(agent_id, "add_rules", rules=[{**RULES[0], "source": None, "quote": None}])


def test_a_message_in_the_conversation_is_the_next_turn(client, scripted):
    model = scripted(
        [ASK],
        BUILD,
        [
            tool("set_task", step="Greeting", task="Say hi and ask what they need."),
            tool("run_all", said="Shortened the greeting in Greeting."),
            {"answer": "Shortened the greeting; all 5 tests still pass.", "links": []},
        ],
    )
    agent_id, pull = _create(client)
    _pick(client, agent_id, pull)

    sent = client.post(
        f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Make the greeting shorter."}
    )
    assert sent.status_code == 200
    settle()

    pull = _pull(client, agent_id)
    assert _types(pull)[-4:] == ["message", "message", "checks", "message"]
    changed = pull["events"][-3]
    assert (changed["text"], changed["changed"], changed["details"]) == (
        "Shortened the greeting in Greeting.",
        True,
        ["Changed what Greeting says"],
    )
    task = pull["config"]["nodes"][0]["task_messages"][0]["content"]
    assert task == "Say hi and ask what they need."
    assert "Their message: Make the greeting shorter." in _told(model)
    assert pull["checks"]["state"] == "passed"


def test_your_own_changes_wait_while_prosper_ai_works(client, scripted, agent):
    scripted([ASK])
    agent_id, _ = _create(client)
    store.prosper.set_state(agent_id, 1, "working", "Drawing the steps")

    saved = client.put(f"/api/agents/{agent_id}/pulls/1", json={"config": agent})
    talked = client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Hello"})
    question = _pull(client, agent_id)["events"][-1]["question"]
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


def test_a_restart_mid_setup_is_picked_up_by_the_next_message(client, scripted):
    # Drawn and given its rules when the server stops.
    model = scripted([ASK], [*BUILD[2:]])
    agent_id, pull = _create(client)
    question = pull["events"][-1]["question"]
    store.prosper.pick(agent_id, 1, question, 0)
    store.prosper.set_state(agent_id, 1, "working", "Writing the rules")
    _edit(agent_id, "draw_agent", agent=DRAFT)
    _edit(agent_id, "add_rules", rules=[*RULES, WAITLIST])

    store.init_db()  # the server starting again

    pull = _pull(client, agent_id)
    assert pull["prosper"]["state"] == "failed"
    assert _types(pull)[-1] == "interrupted"
    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Go on"})
    settle()

    pull = _pull(client, agent_id)
    # It went on from what the copy held: the tests, and the run.
    facts = _told(model)
    assert "Drawn: yes." in facts and "Offer the waitlist if no time works." in facts
    assert len(pull["tests"]) == 5 and len(pull["rules"]) == 3
    assert pull["checks"]["state"] == "passed"
    assert pull["prosper"]["state"] == "done"


def test_when_it_cannot_finish_it_says_so_and_a_message_goes_on(client, scripted):
    # Its script runs out after drawing: the turn fails, and says so.
    scripted([ASK], BUILD[:1])
    agent_id, pull = _create(client)
    pull = _pick(client, agent_id, pull)

    assert pull["prosper"]["state"] == "failed"
    assert pull["events"][-1]["text"].startswith("I couldn't finish: Nothing scripted")
    assert len(pull["config"]["nodes"]) == 3

    scripted(BUILD[1:])
    client.post(f"/api/agents/{agent_id}/pulls/1/messages", json={"text": "Try again"})
    settle()
    assert _pull(client, agent_id)["checks"]["state"] == "passed"


def test_tests_that_fail_are_read_and_the_agent_is_changed(client, scripted, fake_checks):
    # "Never gives advice" is judged: it fails the first run, then passes.
    verdicts = [False] * 3

    async def judge(check, transcript):
        verdict = verdicts.pop(0) if verdicts else True
        return {"pass": verdict, "detail": "Judged.", "tokens": {"prompt": 1, "completion": 1}}

    fake_checks.judge = judge
    model = scripted(
        [ASK],
        [
            *BUILD[:4],
            tool("add_rules", rules=[{**RULES[0], "step": "Greeting", "text": "Refuse advice."}]),
            tool("run_all", said="Added a rule in Greeting: refuse medical advice."),
            DONE,
        ],
    )
    agent_id, pull = _create(client)

    pull = _pick(client, agent_id, pull)

    first = model.asked["work"][-3][-1]["output"]
    assert "1 failing (blocks a merge)" in first
    assert "Asks for advice · failing, 0/3" in first
    assert _types(pull)[-5:] == ["checks", "message", "rule", "checks", "message"]
    said = next(e for e in pull["events"] if e.get("changed"))
    assert said["text"] == "Added a rule in Greeting: refuse medical advice."
    assert pull["checks"]["state"] == "passed"


def test_a_turn_runs_the_suite_three_times_at_most(client, scripted, fake_checks):
    fake_checks.verdict = False  # "Never gives advice" always fails
    model = scripted([ASK], [*BUILD[:4], *[tool("run_all", said="")] * 3, DONE])
    agent_id, pull = _create(client)
    checks.wait()

    _pick(client, agent_id, pull)

    last = model.asked["work"][-1][-1]["output"]
    assert last.startswith("Refused: That was your last round (2 after the first run)")
