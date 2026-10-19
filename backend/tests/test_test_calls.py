#
# Test calls: the voice calls a person places from Build. Recorded by the
# voice pipeline as they go and stored when they end, listed apart from the
# calls callers make, and reviewed by Prosper AI only when asked, without
# filing anything as an issue. No WebRTC, no audio, no OpenAI: the record is
# fed what the pipeline would hand it, and the review comes from a script.
#

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    UserTurnMessageAddedMessage,
)

import api
import bot
from tests.conftest import settle
from tests.test_live import REVIEW


def _node(node, came_from=None, edge=None, **collected):
    return {"type": "node", "node": node, "from": came_from, "edge": edge, "collected": collected}


def _call(record: api.TestCallRecord) -> int:
    """A short booking through the record, as a voice call would hand it over."""
    record.started()
    record.entered(_node("greeting"))
    record.said("agent", "Hi, this is the clinic. Book, reschedule or cancel?")
    record.said("caller", "I'd like to book.")
    record.said("agent", "")  # a turn that only moved on
    record.entered(_node("collect_details", "greeting", "choose_intent", intent="book"))
    record.said("agent", "May I have your name?")
    record.entered(_node("confirm", "collect_details", "record_details", full_name="Ana"))
    record.said("agent", "You're booked. Goodbye!")
    return record.save()


def test_a_test_call_on_live_is_stored_with_its_version_path_and_transcript(client, live_agent):
    agent_id = live_agent()
    body = {"agent_id": agent_id}

    call_id = _call(api.record_for(body, api.agent_for_call(body)))

    listed = client.get(f"/api/agents/{agent_id}/test-calls").json()
    assert [(c["id"], c["pull"], c["version"], c["by"]) for c in listed] == [
        (call_id, None, 1, "you")
    ]
    page = client.get(f"/api/agents/{agent_id}/test-calls/{call_id}").json()
    assert (page["ended"], page["review"], page["seconds"]) == ("agent_ended", "none", 0)
    assert [step["node"] for step in page["path"]] == ["greeting", "collect_details", "confirm"]
    assert page["path"][1]["collected"] == {"intent": "book"}
    assert [(line["role"], line["node"]) for line in page["transcript"]] == [
        ("agent", "greeting"),
        ("caller", "greeting"),
        ("agent", "collect_details"),
        ("agent", "confirm"),
    ]
    # Apart from the calls callers make.
    assert client.get(f"/api/agents/{agent_id}/calls").json()["calls"] == []


def test_a_test_call_on_a_pull_request_names_it_and_one_cut_short_was_hung_up(client, live_agent):
    agent_id = live_agent()
    client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Edits"})
    body = {"agent_id": agent_id, "pull": 2}
    record = api.record_for(body, api.agent_for_call(body))
    record.started()
    record.entered(_node("greeting"))
    record.said("agent", "Hi!")

    call_id = record.save()

    page = client.get(f"/api/agents/{agent_id}/test-calls/{call_id}").json()
    assert (page["pull"], page["version"], page["ended"]) == (2, None, "caller_hung_up")


def test_a_call_nobody_joined_and_a_call_to_the_sample_are_not_stored(client, live_agent):
    agent_id = live_agent()
    body = {"agent_id": agent_id}

    assert api.record_for(body, api.agent_for_call(body)).save() is None
    assert api.record_for(None, api.agent_for_call(None)) is None
    assert client.get(f"/api/agents/{agent_id}/test-calls").json() == []


def test_the_record_takes_both_sides_turns_from_the_context_aggregators(live_agent):
    agent_id = live_agent()
    body = {"agent_id": agent_id}
    record = api.record_for(body, api.agent_for_call(body))
    pair = LLMContextAggregatorPair(LLMContext())
    record.listen(pair)

    async def turns():
        user, assistant = pair.user(), pair.assistant()
        said = AssistantTurnStoppedMessage(content="Hello!", timestamp="", interrupted=False)
        await assistant._call_event_handler("on_assistant_turn_stopped", said)
        heard = UserTurnMessageAddedMessage(content="Hi, I want to book.", timestamp="")
        await user._call_event_handler("on_user_turn_message_added", heard)

    asyncio.run(turns())

    assert [(line["role"], line["text"]) for line in record.transcript] == [
        ("agent", "Hello!"),
        ("caller", "Hi, I want to book."),
    ]


def test_the_bot_hands_a_test_call_its_record(client, live_agent, monkeypatch):
    agent_id = live_agent()
    client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Edits"})
    records = []

    async def run_bot(transport, runner_args, builder, record=None):
        records.append(record)

    monkeypatch.setattr(bot, "run_bot", run_bot)
    monkeypatch.setattr(bot, "create_transport", AsyncMock())

    asyncio.run(bot.bot(SimpleNamespace(body={"agent_id": agent_id, "pull": 2})))
    asyncio.run(bot.bot(SimpleNamespace(body=None)))

    assert [(r.agent_id, r.pull) if r else None for r in records] == [(agent_id, 2), None]


def test_prosper_ai_reviews_a_test_call_when_asked_and_files_no_issue(
    client, live_agent, prosper_model
):
    agent_id = live_agent()
    body = {"agent_id": agent_id}
    call_id = _call(api.record_for(body, api.agent_for_call(body)))
    review = copy.deepcopy(REVIEW)
    review["findings"][0].update(turn=2, quote="your name")
    prosper_model.script = {"audit": [review]}
    url = f"/api/agents/{agent_id}/test-calls/{call_id}"

    started = client.post(f"{url}/review")
    settle()

    assert (started.status_code, started.json()["review"]) == (202, "pending")
    page = client.get(url).json()
    assert (page["review"], page["outcome"], page["flagged"]) == ("done", "booked", 1)
    (finding,) = page["findings"]
    assert (finding["step"], finding["turn"]) == ("collect_details", 2)
    assert client.get(f"/api/agents/{agent_id}/issues").json() == []
    assert "testing the agent by voice" in prosper_model.asked["audit"][0][-1]["content"]


def test_a_failed_review_says_so_and_can_be_asked_again(client, live_agent, prosper_model):
    agent_id = live_agent()
    body = {"agent_id": agent_id}
    call_id = _call(api.record_for(body, api.agent_for_call(body)))
    url = f"/api/agents/{agent_id}/test-calls/{call_id}"

    client.post(f"{url}/review")  # nothing scripted: the model fails
    settle()

    assert client.get(url).json()["review"] == "failed"
    assert client.post(f"{url}/review").status_code == 202
    settle()
    assert client.post(f"/api/agents/{agent_id}/test-calls/99/review").status_code == 404
