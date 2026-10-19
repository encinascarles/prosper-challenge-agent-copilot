#
# Calls and issues as the store keeps them: a call joins the issues of its
# findings, issues share the pull requests' counter, and a snooze ends on its own.
#

import json

import pytest

import store
from store.db import Conflict, connect

CALL = {
    "ended": "agent_ended",
    "path": [{"node": "greeting", "from": None, "edge": None, "collected": {}}],
    "transcript": [
        {"role": "agent", "text": "Hi, how can I help?", "node": "greeting"},
        {"role": "caller", "text": "I have chest pain, can I book?", "node": "greeting"},
        {"role": "agent", "text": "Sure, what day suits you?", "node": "greeting"},
    ],
}
FINDING = {
    "check": "Sends urgent symptoms to emergency services",
    "step": "greeting",
    "turn": 2,
    "quote": "Sure, what day suits you?",
    "why": "Chest pain needs 911, not a booking.",
    "title": "Books a caller with chest pain",
    "severity": "safety",
    "description": "The agent books callers who describe urgent symptoms.",
}


def _call(agent_id: str, caller: str = "Ana Ruiz") -> int:
    return store.calls.add_call(agent_id, None, 1, caller, "You are Ana.", CALL, 20, {})


def test_a_call_lists_the_issues_its_findings_joined(client, live_agent):
    agent_id = live_agent()
    first, second = _call(agent_id), _call(agent_id, "Tom Lee")
    issue = store.issues.file_finding(agent_id, first, "Ana Ruiz", FINDING)
    assert store.issues.file_finding(agent_id, second, "Tom Lee", FINDING, issue) == issue

    assert [c["issues"] for c in store.calls.list_calls(agent_id)] == [[issue], [issue]]
    found = store.issues.get_issue(agent_id, issue)
    assert found["calls"] == 2
    assert [e["type"] for e in found["events"]] == ["opened", "seen"]
    # The bad turn, with the caller's line before it.
    assert [line["index"] for line in found["findings"][0]["lines"]] == [1, 2]
    assert store.calls.get_call(agent_id, first)["findings"][0]["title"] == FINDING["title"]


def test_issues_take_numbers_from_the_pull_requests_counter(client, live_agent):
    agent_id = live_agent()  # PR #1 merged
    issue = store.issues.file_finding(agent_id, _call(agent_id), "Ana Ruiz", FINDING)
    assert issue == 2
    assert store.open_pull(agent_id, "Your edits", "edit", "you")["number"] == 3
    assert store.get_agent(agent_id)["open_issues"] == 1


def test_a_resolved_issue_takes_no_more_calls(client, live_agent):
    agent_id = live_agent()
    issue = store.issues.file_finding(agent_id, _call(agent_id), "Ana Ruiz", FINDING)
    store.issues.resolve(agent_id, issue, "you")
    with pytest.raises(Conflict):
        store.issues.file_finding(agent_id, _call(agent_id), "Tom Lee", FINDING, issue)
    # Ignored keeps counting.
    store.issues.reopen(agent_id, issue, "you")
    store.issues.ignore(agent_id, issue, "you")
    store.issues.file_finding(agent_id, _call(agent_id), "Tom Lee", FINDING, issue)
    assert store.issues.get_issue(agent_id, issue)["calls"] == 2


def test_a_snooze_ends_on_its_own(client, live_agent):
    agent_id = live_agent()
    issue = store.issues.file_finding(agent_id, _call(agent_id), "Ana Ruiz", FINDING)
    assert store.issues.snooze(agent_id, issue, "day", "you")["state"] == "snoozed"
    with connect() as conn:
        conn.execute(
            "UPDATE issues SET snooze = ? WHERE number = ?",
            (json.dumps({"until": "2000-01-01T00:00:00.000+00:00"}), issue),
        )
    woken = store.issues.get_issue(agent_id, issue)
    assert woken["state"] == "open"
    assert woken["events"][-1]["type"] == "woke"


def test_until_the_next_version_ends_when_one_goes_live(client, live_agent):
    agent_id = live_agent()
    issue = store.issues.file_finding(agent_id, _call(agent_id), "Ana Ruiz", FINDING)
    store.issues.snooze(agent_id, issue, "version", "you")
    assert store.issues.get_issue(agent_id, issue)["state"] == "snoozed"
    with connect() as conn:
        conn.execute(
            "INSERT INTO versions (agent_id, number, config, layout, created_at)"
            " SELECT agent_id, 2, config, layout, created_at FROM versions WHERE agent_id = ?",
            (agent_id,),
        )
    assert store.issues.get_issue(agent_id, issue)["state"] == "open"


def test_only_one_batch_of_calls_at_a_time(client, live_agent, new_agent):
    agent_id = live_agent()
    play = store.calls.start_play(agent_id)
    with pytest.raises(Conflict):
        store.calls.start_play(agent_id)
    store.calls.update_play(play["id"], state="done")
    store.calls.start_play(agent_id)
    draft, _ = new_agent("Not live")
    with pytest.raises(Conflict):
        store.calls.start_play(draft)


def test_a_restart_stops_the_batch_it_cut(client, live_agent):
    agent_id = live_agent()
    store.calls.start_play(agent_id)
    call = _call(agent_id)
    store.init_db()
    assert store.calls.latest_play(agent_id)["state"] == "stopped"
    assert store.calls.get_call(agent_id, call)["review"] == "failed"
