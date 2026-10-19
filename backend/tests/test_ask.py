#
# Ask Prosper AI, through the API: a question answered from the agent's facts,
# a change asked for becoming a card, and the card opening a pull request
# where Prosper AI writes a test, makes the change and runs the suite, as on
# a fix. The model is scripted and the calls run on fakes: nothing here
# reaches OpenAI. Its other tools: test_ask_tools.py.
#

import copy

import pytest

import store
from api import checks
from copilot import artifacts, ask
from tests.conftest import settle
from tests.fakes import tool
from tests.test_fix import EXAMPLE, ISSUE, two_callers, verdicts, with_issue  # noqa: F401

ANSWER = {
    "answer": "No: Collect details only asks for the caller's own name and reason.",
    "links": [],
}
CHANGE_ASKED = {
    "title": "Ask who the visit is for",
    "what": "Collect details asks whether the visit is for the caller or someone else.",
}
PROPOSE = tool("open_pull_request", **CHANGE_ASKED)
# What Prosper AI says once the pull request is open: nothing the card does not.
NOTHING_MORE = {"answer": "", "links": []}
TEST = {
    "name": "Asks who the visit is for",
    "caller": "You are Ana Ruiz and you want to book a check-up for your son Leo.",
    "checks": ["Reaches Offer times", "Asks who the visit is for"],
}
RULE = {
    "step": "Collect details",
    "text": "Ask whether the visit is for the caller or someone else.",
}
CHANGE = {
    "reply": "Added a rule in Collect details: ask who the visit is for.",
    "agent": artifacts.from_config(EXAMPLE),
    "rules": [RULE],
}


def _ask(client, agent_id, text, chat=None, pull=None, status=None):
    body = {"text": text, "pull": pull}
    if chat is None:
        response = client.post(f"/api/agents/{agent_id}/chats", json=body)
    else:
        response = client.post(f"/api/agents/{agent_id}/chats/{chat}/messages", json=body)
    assert response.status_code == (status or (201 if chat is None else 200)), response.text
    return response.json()


def test_a_question_is_answered_from_the_live_agent_and_titles_the_chat(
    client, live_agent, prosper_model
):
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER]}

    chat = _ask(client, agent_id, "Can Dental Recall book for a child?")

    assert chat["title"] == "Can Dental Recall book for a child?"
    you, answer = chat["messages"]
    assert (you["by"], you["text"]) == ("you", "Can Dental Recall book for a child?")
    assert (answer["by"], answer["text"], answer["about"]) == ("Prosper AI", ANSWER["answer"], "v1")
    assert answer["offer"] is None
    # What it was given: the live agent, its steps and the question.
    [asked] = prosper_model.asked["ask"]
    facts = asked[1]["content"]
    assert "The person is looking at live, v1" in facts
    assert '"name": "collect_details"' in facts
    assert facts.endswith("Their question: Can Dental Recall book for a child?")

    [listed] = client.get(f"/api/agents/{agent_id}/chats").json()
    assert (listed["id"], listed["count"], listed["pulls"]) == (chat["id"], 2, [])


def test_an_answer_that_names_a_step_as_stored_or_links_nothing_is_sent_back(
    client, live_agent, prosper_model
):
    agent_id = live_agent()
    stored = {**ANSWER, "answer": "No: collect_details only asks for the caller's name."}
    dangling = {**ANSWER, "links": [{"kind": "issue", "number": 9}]}
    prosper_model.script = {"ask": [stored, dangling, ANSWER]}

    chat = _ask(client, agent_id, "Can it book for a child?")

    assert chat["messages"][-1]["text"] == ANSWER["answer"]
    first, second = prosper_model.asked["ask"][1:]
    assert 'never "collect_details"' in first[-1]["content"]
    assert "There is no Issue #9" in second[-1]["content"]


def test_it_says_in_the_chat_when_it_cannot_answer(client, live_agent, prosper_model):
    agent_id = live_agent()
    long = {**ANSWER, "answer": "No. " * 200}
    prosper_model.script = {"ask": [long, long, long]}

    chat = _ask(client, agent_id, "Can it book for a child?")

    answer = chat["messages"][-1]
    assert answer["failed"] is True
    assert answer["text"].startswith("I couldn't answer that: The answer is 799 characters")


def test_a_call_the_question_names_is_given_whole(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {
        "ask": [
            {**ANSWER, "links": [{"kind": "issue", "number": ISSUE}, {"kind": "call", "number": 1}]}
        ]
    }

    chat = _ask(client, agent_id, "Why did Ana's call get offered Thursday?")

    facts = prosper_model.asked["ask"][0][1]["content"]
    assert f"Issue #{ISSUE} · open · found in calls · booking · step offer_times · 2 calls" in facts
    assert "The calls this chat is about, in full:" in facts
    assert "who they were: You are Ana Ruiz, for a check-up." in facts
    assert "I can offer Tuesday at 10 AM or Thursday at 2 PM." in facts
    # Tom Lee's call is listed, not given whole.
    assert "who they were: You are Tom Lee" not in facts
    assert chat["messages"][-1]["links"] == [
        {"kind": "issue", "number": ISSUE},
        {"kind": "call", "number": 1},
    ]


def test_a_change_asked_for_is_a_card_and_changes_nothing(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER, PROPOSE]}
    chat = _ask(client, agent_id, "Can it book for a child?")

    chat = _ask(client, agent_id, "Yes, have it ask who the visit is for.", chat=chat["id"])

    message = chat["messages"][-1]
    assert message["text"] == ""
    assert message["action"] == {
        "tool": "open_pull_request",
        "title": "Open a pull request",
        "what": CHANGE_ASKED["title"],
        "meta": [CHANGE_ASKED["what"], "On v1 · nothing goes live until you merge"],
        "state": "pending",
        "result": None,
        "error": None,
    }
    # The chat so far went with the request.
    facts = prosper_model.asked["ask"][1][1]["content"]
    assert f"You: {ANSWER['answer']}" in facts
    # Nothing was opened, and live is as it was.
    assert [p["number"] for p in client.get(f"/api/agents/{agent_id}/pulls").json()] == [1]


@pytest.fixture
def offered(client, live_agent, prosper_model):
    """A live agent and a chat whose last message proposes a pull request: (agent id, chat)."""
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER, PROPOSE]}
    chat = _ask(client, agent_id, "Can it book for a child?")
    chat = _ask(client, agent_id, "Yes, have it ask who the visit is for.", chat=chat["id"])
    return agent_id, chat


def _take(client, agent_id, chat, status=200, index=None):
    index = len(chat["messages"]) - 1 if index is None else index
    response = client.post(
        f"/api/agents/{agent_id}/chats/{chat['id']}/messages/{index}/action", json={"do": True}
    )
    assert response.status_code == status, response.text
    settle()
    return response.json()


def _opened(chat: dict, index: int) -> int:
    return chat["messages"][index]["action"]["result"]["link"]["number"]


def test_the_offer_opens_a_change_where_a_test_fails_first_then_passes(
    client,
    offered,
    prosper_model,
    verdicts,  # noqa: F811
):
    agent_id, chat = offered
    prosper_model.script = {
        "ask": [NOTHING_MORE],
        "capture": [TEST],
        "fix": [copy.deepcopy(CHANGE)],
    }
    verdicts += [False, False, False]  # the new test fails on v1, all three calls

    index = len(chat["messages"]) - 1
    opened = _take(client, agent_id, chat)
    number = _opened(opened, index)
    pull = client.get(f"/api/agents/{agent_id}/pulls/{number}").json()

    assert (pull["kind"], pull["title"], pull["base_version"]) == (
        "change",
        "Ask who the visit is for",
        1,
    )
    assert pull["chat"] == {"id": chat["id"], "title": "Can it book for a child?"}
    types = [event["type"] for event in pull["events"]]
    assert types == ["request", "opened", "reproduced", "proposed", "rule", "checks", "proved"]
    assert pull["events"][0]["text"] == "Yes, have it ask who the visit is for."
    assert pull["events"][1]["chat"] == chat["id"]
    assert pull["events"][2]["text"] == "Wrote a test of it: it fails on v1 as it is · 0/3"
    [test] = pull["tests"]
    assert test["source"] == {
        "kind": "request",
        "pull": number,
        "file": None,
        "quote": "Yes, have it ask who the visit is for.",
        "before": {"version": 1, "passed": 0, "runs": 3},
    }
    [rule] = pull["rules"]
    assert (rule["step"], rule["source"]["kind"]) == ("collect_details", "request")
    assert pull["checks"]["state"] == "passed"
    assert pull["events"][-1]["text"] == (
        "All checks passed · 1/1 · 3 runs each · the new test 0/3 on v1 → 3/3"
    )
    # The test was written from the person's words and the card.
    capture = prosper_model.asked["capture"][0][1]["content"]
    assert '"Yes, have it ask who the visit is for."' in capture
    assert CHANGE_ASKED["what"] in capture

    # The card says which pull request it opened, and opens no other.
    assert opened["messages"][index]["action"]["result"]["text"] == f"Opened PR #{number}"
    assert len(opened["messages"]) == index + 1  # Prosper AI had nothing to add
    assert client.get(f"/api/agents/{agent_id}/chats").json()[0]["pulls"] == [number]
    again = _take(client, agent_id, chat, status=409, index=index)
    assert again["detail"] == "That was done already."

    merged = client.post(f"/api/agents/{agent_id}/pulls/{number}/merge")
    assert merged.status_code == 200, merged.text
    assert merged.json()["merged_version"] == 2


def test_when_the_test_already_passes_it_says_so_and_asks_whether_to_go_on(
    client, offered, prosper_model
):
    agent_id, chat = offered
    # One try: the judge passes it.
    prosper_model.script = {"ask": [NOTHING_MORE], "capture": [TEST]}

    number = _opened(_take(client, agent_id, chat), len(chat["messages"]) - 1)
    pull = client.get(f"/api/agents/{agent_id}/pulls/{number}").json()

    message, question = pull["events"][-2:]
    assert message["text"] == (
        "The test of it already passes on v1: 3/3. The agent may do this already."
    )
    assert question["text"] == "Propose the change anyway, with the test I wrote?"
    assert pull["prosper"]["state"] == "waiting"
    assert len(prosper_model.asked["capture"]) == 1


def test_a_message_that_proposes_nothing_does_nothing(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER]}
    chat = _ask(client, agent_id, "Can it book for a child?")

    response = _take(client, agent_id, chat, status=409)

    assert response["detail"] == "That message proposes nothing to do."


def test_an_older_chats_offer_still_opens_its_pull_request(client, live_agent, prosper_model):
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER], "capture": [TEST]}
    chat = _ask(client, agent_id, "Have it ask who the visit is for.")
    offer = {"by": "Prosper AI", "text": "I can.", "offer": {**CHANGE_ASKED, "pull": None}}
    chat = store.chats.add_message(agent_id, chat["id"], offer)
    index = len(chat["messages"]) - 1

    response = client.post(f"/api/agents/{agent_id}/chats/{chat['id']}/messages/{index}/pull")
    settle()

    assert response.status_code == 201, response.text
    number = response.json()["pull"]["number"]
    assert response.json()["chat"]["messages"][index]["offer"]["pull"] == number
    assert client.get(f"/api/agents/{agent_id}/chats").json()[0]["pulls"] == [number]


def test_a_question_from_a_pull_request_is_answered_from_its_copy(client, new_agent, prosper_model):
    agent_id, pull = new_agent()  # not live: its PR #1
    prosper_model.script = {"ask": [ANSWER]}

    chat = _ask(client, agent_id, "What does it ask first?", pull=pull["number"])

    assert chat["messages"][-1]["about"] == "PR #1"
    facts = prosper_model.asked["ask"][0][1]["content"]
    assert "Live: nothing yet. The person is looking at PR #1" in facts


def test_titles_are_the_first_question_on_one_line():
    assert (
        ask.store.chats.title_of("  Can she\nbook   for a child? ") == "Can she book for a child?"
    )
    long = "Why " + "did the call go there " * 6
    title = ask.store.chats.title_of(long)
    assert len(title) <= 80 and title.endswith("…")


def test_a_change_names_its_own_test_not_one_a_fix_left_in_live(
    client,
    new_agent,
    prosper_model,
    verdicts,  # noqa: F811
):
    # Live keeps the first test of a fix merged into it, with its own "before".
    agent_id, _ = new_agent()
    earlier = {
        **TEST,
        "name": "Offers only open times",
        "source": {
            "kind": "issue",
            "pull": 1,
            "issue": 9,
            "before": {"version": 0, "passed": 1, "runs": 3},
        },
    }
    store.prosper.write(agent_id, 1, {"type": "test", "by": "you", "at": "now"}, tests=(earlier,))
    checks.start(agent_id, pull=1)
    settle()
    assert client.post(f"/api/agents/{agent_id}/pulls/1/merge").status_code == 200
    prosper_model.script = {
        "ask": [PROPOSE, NOTHING_MORE],
        "capture": [TEST],
        "fix": [copy.deepcopy(CHANGE)],
    }
    chat = _ask(client, agent_id, "Have it ask who the visit is for.")
    verdicts += [False, False, False]

    number = _opened(_take(client, agent_id, chat), 1)

    pull = client.get(f"/api/agents/{agent_id}/pulls/{number}").json()
    assert pull["events"][-1]["text"].endswith("the new test 0/3 on v1 → 3/3")
    proposal = prosper_model.asked["fix"][0][1]["content"]
    assert "must make pass: Asks who the visit is for" in proposal


def test_a_question_about_a_pull_request_that_does_not_exist_stores_nothing(
    client, live_agent, prosper_model
):
    agent_id = live_agent()

    missing = _ask(client, agent_id, "What does it ask first?", pull=99, status=404)

    assert missing["detail"] == "The agent has no PR #99."
    assert client.get(f"/api/agents/{agent_id}/chats").json() == []
    assert "ask" not in prosper_model.asked


def test_a_further_question_about_nothing_leaves_the_chat_as_it_was(
    client, live_agent, prosper_model
):
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER]}
    chat = _ask(client, agent_id, "Can it book for a child?")

    _ask(client, agent_id, "And on PR #99?", chat=chat["id"], pull=99, status=404)

    after = client.get(f"/api/agents/{agent_id}/chats/{chat['id']}").json()
    assert after["messages"] == chat["messages"]
