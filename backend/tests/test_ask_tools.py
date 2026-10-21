#
# Ask Prosper AI's tools: a read runs at once and its result goes back to the
# model; an act waits on its card until the person says Do it or Cancel; a
# refusal goes back as the tool's answer; a message makes a bounded number of
# tool calls; a waiting card outlives a restart. And every act is the route
# the UI calls, not a copy of it. The run is the Agents SDK's own; only its
# model is scripted: nothing here reaches OpenAI.
#

import json

import agents
import pytest

import store
from api import live, pulls, suite, tools
from copilot import agent
from tests.conftest import settle
from tests.fakes import tool
from tests.test_fix import (  # noqa: F401
    ISSUE,
    fixed_at,
    two_callers,
    verdicts,
    with_issue,
)

ANSWER = {"answer": "Issue #2 is about the times offered.", "links": []}
NOTHING_MORE = {"answer": "", "links": []}
SNOOZE = tool("change_issues", change="snooze", issues=[ISSUE], until="week")


def _ask(client, agent_id, text, chat=None):
    if chat is None:
        response = client.post(f"/api/agents/{agent_id}/chats", json={"text": text})
    else:
        response = client.post(f"/api/agents/{agent_id}/chats/{chat}/messages", json={"text": text})
    assert response.status_code in (200, 201), response.text
    return response.json()


def _decide(client, agent_id, chat, index, do=True, status=200):
    response = client.post(
        f"/api/agents/{agent_id}/chats/{chat['id']}/messages/{index}/action", json={"do": do}
    )
    assert response.status_code == status, response.text
    settle()
    return response.json()


def _state(client, agent_id, number=ISSUE):
    return client.get(f"/api/agents/{agent_id}/issues/{number}").json()["state"]


def test_a_read_runs_at_once_and_its_result_goes_back(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [tool("read_issue", number=ISSUE), ANSWER]}

    chat = _ask(client, agent_id, "What is Issue #2 about?")

    message = chat["messages"][-1]
    assert message["text"] == ANSWER["answer"]
    assert message["reads"] == ["Read Issue #2 and its 2 calls"]
    assert message["action"] is None
    # The second request has the call and what it read, in plain lines.
    *_, called, read = prosper_model.asked["ask"][1]
    assert called["type"] == "function_call" and called["name"] == "read_issue"
    assert read["type"] == "function_call_output"
    assert read["call_id"] == called["call_id"]
    assert read["output"].startswith("- Issue #2 · open · found in calls")
    assert "Its calls, latest first:\n- call 2 ·" in read["output"]


def test_an_act_waits_for_do_it_then_runs_and_goes_on(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE]}

    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")

    index = len(chat["messages"]) - 1
    action = chat["messages"][index]["action"]
    assert (action["title"], action["meta"], action["state"]) == (
        "Snooze Issue #2",
        ["For a week"],
        "pending",
    )
    assert action["what"]  # the issue's title
    assert _state(client, agent_id) == "open"  # nothing happens without the click

    prosper_model.script = {"ask": [{"answer": "It comes back next week.", "links": []}]}
    chat = _decide(client, agent_id, chat, index)

    assert _state(client, agent_id) == "snoozed"
    done = chat["messages"][index]["action"]
    assert (done["state"], done["result"]) == (
        "done",
        {"text": "Snoozed Issue #2", "link": {"kind": "issue", "number": ISSUE}},
    )
    assert chat["messages"][-1]["text"] == "It comes back next week."
    # The model went on from the conversation it stopped in, with the result.
    resumed = prosper_model.asked["ask"][-1]
    assert resumed[1]["content"].startswith("Now: ")  # the same facts, first
    assert resumed[-1] == {
        "type": "function_call_output",
        "call_id": resumed[-2]["call_id"],
        "output": "Snoozed Issue #2",
    }
    # The issue's log says the person did it: they clicked.
    issue = client.get(f"/api/agents/{agent_id}/issues/{ISSUE}").json()
    assert issue["events"][-1]["by"] == "you"


def test_cancel_does_nothing_and_the_next_question_says_so(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")
    index = len(chat["messages"]) - 1
    asked = len(prosper_model.asked["ask"])

    chat = _decide(client, agent_id, chat, index, do=False)

    assert chat["messages"][index]["action"]["state"] == "declined"
    assert _state(client, agent_id) == "open"
    assert len(prosper_model.asked["ask"]) == asked  # no request for a cancel
    prosper_model.script = {"ask": [ANSWER]}
    _ask(client, agent_id, "What is it about, then?", chat=chat["id"])
    facts = prosper_model.asked["ask"][-1][1]["content"]
    assert "[proposed: Snooze Issue #2" in facts
    assert "they declined it, nothing was done]" in facts
    _decide(client, agent_id, chat, index, status=409)


def test_a_card_left_when_the_person_writes_again_is_skipped(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE, ANSWER]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")
    index = len(chat["messages"]) - 1

    chat = _ask(client, agent_id, "Actually, what is it about?", chat=chat["id"])

    assert chat["messages"][index]["action"]["state"] == "skipped"
    refused = _decide(client, agent_id, chat, index, status=409)
    assert refused["detail"] == "That was left behind already."
    assert _state(client, agent_id) == "open"


def test_a_refused_tool_goes_back_to_the_model_in_the_routes_words(
    client,
    with_issue,  # noqa: F811
    prosper_model,
):
    agent_id = with_issue()
    prosper_model.script = {
        "ask": [
            tool("read_issue", number=99),
            # A card the act would be refused for is never shown: PR #1 merged.
            tool("merge_pull", number=1),
            ANSWER,
        ]
    }

    chat = _ask(client, agent_id, "Merge it.")

    assert chat["messages"][-1]["text"] == ANSWER["answer"]
    assert chat["messages"][-1]["action"] is None
    outputs = [i["output"] for i in prosper_model.asked["ask"][-1] if "output" in i]
    assert outputs == ["Refused: The agent has no Issue #99.", "Refused: PR #1 is merged."]


def test_an_act_refused_on_do_it_says_why_and_tells_the_model(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")
    index = len(chat["messages"]) - 1
    # Meanwhile, someone resolved it from the Issues page.
    assert client.post(f"/api/agents/{agent_id}/issues/{ISSUE}/resolve").status_code == 200

    prosper_model.script = {"ask": [{"answer": "Someone resolved it already.", "links": []}]}
    chat = _decide(client, agent_id, chat, index)

    action = chat["messages"][index]["action"]
    assert (action["state"], action["error"]) == ("failed", "Issue #2 is resolved.")
    assert prosper_model.asked["ask"][-1][-1]["output"] == "Refused: Issue #2 is resolved."
    assert chat["messages"][-1]["text"] == "Someone resolved it already."


def test_a_message_makes_a_bounded_number_of_tool_calls(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    reads = [tool("list_versions")] * agent.MAX_TOOL_CALLS
    prosper_model.script = {"ask": [*reads, ANSWER]}

    chat = _ask(client, agent_id, "Read everything.")

    assert chat["messages"][-1]["text"] == ANSWER["answer"]
    assert prosper_model.tools[-agent.MAX_TOOL_CALLS - 1 :] == [True] * agent.MAX_TOOL_CALLS + [
        False
    ]


def test_after_an_act_it_may_have_nothing_to_add(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE, NOTHING_MORE]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")

    chat = _decide(client, agent_id, chat, len(chat["messages"]) - 1)

    assert chat["messages"][-1]["action"]["state"] == "done"


def test_an_issue_opened_from_a_chat_is_one_a_person_reported(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    report = tool(
        "open_issue",
        title="Books under the parent's name",
        description="The clinic emailed: a mother booked for her son, booked in her name.",
        step="collect_details",
        severity="booking",
        reported="clinic",
        calls=[],
    )
    prosper_model.script = {"ask": [report, NOTHING_MORE]}
    chat = _ask(client, agent_id, "Open an issue for this: the clinic emailed…")
    index = len(chat["messages"]) - 1
    card = chat["messages"][index]["action"]
    assert (card["title"], card["what"], card["meta"]) == (
        "Open issue",
        "Books under the parent's name",
        ["Collect details", "Booking", "Flagged by the clinic"],
    )

    chat = _decide(client, agent_id, chat, index)

    number = chat["messages"][index]["action"]["result"]["link"]["number"]
    issue = client.get(f"/api/agents/{agent_id}/issues/{number}").json()
    assert (issue["title"], issue["reported"], issue["step"]) == (
        "Books under the parent's name",
        "clinic",
        "collect_details",
    )


def test_a_merge_card_says_what_follows(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    pull = client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Your edits"}).json()
    rule = {"step": None, "text": "Never give medical advice."}
    client.post(f"/api/agents/{agent_id}/pulls/{pull['number']}/rules", json=rule)
    settle()
    prosper_model.script = {"ask": [tool("merge_pull", number=pull["number"]), NOTHING_MORE]}
    chat = _ask(client, agent_id, "Merge it.")
    index = len(chat["messages"]) - 1

    card = chat["messages"][index]["action"]
    assert card["title"] == f"Merge PR #{pull['number']} as v2"
    assert card["meta"][0] == "Calls will use v2 from then on"
    chat = _decide(client, agent_id, chat, index)

    assert chat["messages"][index]["action"]["result"]["text"] == (
        f"Merged PR #{pull['number']} · v2 is live"
    )
    assert client.get(f"/api/agents/{agent_id}").json()["live_version"] == 2


def test_a_merge_card_says_the_warnings_and_do_it_confirms_them(
    client,
    fixed_at,  # noqa: F811
    prosper_model,
):
    agent_id, pull = fixed_at([False, True, True], [False, True, True])
    number = pull["number"]
    prosper_model.script = {"ask": [tool("merge_pull", number=number), NOTHING_MORE]}
    chat = _ask(client, agent_id, "Merge the fix.")
    index = len(chat["messages"]) - 1

    card = chat["messages"][index]["action"]
    assert card["warnings"] == pull["warnings"] != []
    chat = _decide(client, agent_id, chat, index)

    assert chat["messages"][index]["action"]["state"] == "done"
    assert client.get(f"/api/agents/{agent_id}").json()["live_version"] == 2
    issue = client.get(f"/api/agents/{agent_id}/issues/{ISSUE}").json()
    assert issue["events"][-1]["text"] == "merged with its test at 2/3"


# Each act, with arguments, and the route functions the UI calls for it.
ACTS = [
    ("open_issue", {"title": "T", "description": "D", "step": None, "severity": None,
                    "reported": "you", "calls": []}, [(live, "report_issue")]),
    ("tidy_issue", {"number": 1}, [(live, "tidy_issue"), (live, "edit_issue")]),
    ("fix_issue", {"number": 1}, [(live, "fix")]),
    ("open_pull_request", {"title": "T", "what": "W"},
     [(store.chats, "open_change"), (tools.agent, "start")]),
    ("run_tests", {"pull": None, "test": None}, [(suite, "run_version_checks")]),
    ("run_tests", {"pull": None, "test": "Books an appointment"}, [(suite, "run_version_test")]),
    ("run_tests", {"pull": 2, "test": None}, [(suite, "run_pull_checks")]),
    ("run_tests", {"pull": 2, "test": "Books an appointment"}, [(suite, "run_pull_test")]),
    ("play_calls", {}, [(live, "play_calls")]),
    ("change_issues", {"change": "snooze", "issues": [1], "until": "day"}, [(live, "snooze")]),
    ("change_issues", {"change": "resolve", "issues": [1], "until": None}, [(live, "resolve")]),
    ("change_issues", {"change": "ignore", "issues": [1], "until": None}, [(live, "ignore")]),
    ("change_issues", {"change": "reopen", "issues": [1], "until": None}, [(live, "reopen")]),
    ("change_pull", {"change": "close", "number": 2}, [(pulls, "close_pull")]),
    ("change_pull", {"change": "reopen", "number": 2}, [(pulls, "reopen_pull")]),
    ("merge_pull", {"number": 2}, [(pulls, "merge_pull")]),
    ("add_rule", {"pull": 2, "step": None, "text": "R"}, [(suite, "add_rule")]),
    ("add_test", {"pull": 2, "name": "N", "caller": "C", "checks": ["K"]}, [(suite, "add_test")]),
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "args", "routes"), ACTS, ids=[f"{a[0]}-{i}" for i, a in enumerate(ACTS)]
)
def test_every_act_is_the_route_the_ui_calls(client, new_agent, monkeypatch, name, args, routes):
    agent_id, _ = new_agent()
    test = {"name": "Books an appointment", "caller": "Ana books.", "checks": ["Ends the call"]}
    client.post(f"/api/agents/{agent_id}/pulls/1/tests", json=test)
    settle()
    assert client.post(f"/api/agents/{agent_id}/pulls/1/merge").status_code == 200
    client.post(f"/api/agents/{agent_id}/pulls", json={"title": "Your edits"})  # PR #2
    settle()
    called = []
    # What the routes answer, enough for the card's words: a record of anything.
    record = {
        "number": 2,
        "title": "T",
        "merged_version": 2,
        "fixes": None,
        "version": 1,
        "step": "",
        "severity": "booking",
        "calls": [],
        "alone": None,
    }
    for module, function in routes:
        monkeypatch.setattr(
            module, function, lambda *a, _f=function: called.append(_f) or {**record}
        )

    done = tools.TOOLS[name].act(agent_id, args, {"chat": 1, "message": 1})

    assert called == [function for _, function in routes]
    assert done["text"]


READS = [
    ("search_calls", {"caller": None, "outcome": None, "issue": ISSUE, "version": 1, "day": None}),
    ("read_call", {"call": 1}),
    ("list_issues", {"state": "open"}),
    ("read_issue", {"number": ISSUE}),
    ("list_pulls", {"state": None}),
    ("read_pull", {"number": 1}),
    ("read_tests", {"pull": None}),
    ("read_agent", {"pull": None, "version": None}),
    ("read_agent", {"pull": None, "version": 1}),
    ("list_versions", {}),
]


@pytest.mark.parametrize(("name", "args"), READS, ids=[f"{r[0]}-{i}" for i, r in enumerate(READS)])
def test_every_read_answers_in_plain_lines(client, with_issue, name, args):  # noqa: F811
    agent_id = with_issue()

    output, line = tools.TOOLS[name].read(agent_id, args)

    assert output and not output.lstrip().startswith(("{", "["))
    assert line[0].isupper() and "\n" not in line


def test_a_search_says_what_it_found(client, with_issue):  # noqa: F811
    agent_id = with_issue()
    args = {"caller": None, "outcome": None, "issue": ISSUE, "version": None, "day": None}

    output, line = tools.TOOLS["search_calls"].read(agent_id, args)

    assert line == f"Found 2 calls · Issue #{ISSUE}"
    assert output.startswith("2 calls, latest first:\n- call 2 ·")


def test_a_pull_request_opened_is_linked_even_if_prosper_ai_cannot_start(
    client, live_agent, prosper_model, monkeypatch
):
    agent_id = live_agent()
    prosper_model.script = {"ask": [ANSWER]}
    chat = _ask(client, agent_id, "Have it ask who the visit is for.")

    def broken(*args):
        raise RuntimeError("the job pool is shut down")

    monkeypatch.setattr(tools.agent, "start", broken)
    args = {"title": "Ask who the visit is for", "what": "Collect details asks it."}
    done = tools.TOOLS["open_pull_request"].act(agent_id, args, {"chat": chat["id"], "message": 1})

    assert done["link"] == {"kind": "pull", "number": 2}
    assert done["text"] == (
        "Opened PR #2 · Prosper AI could not start: the job pool is shut down"
        " · write to it to retry"
    )
    # Failed, like work cut by a restart: a message to it goes on.
    assert store.prosper.work_of(agent_id, 2)["state"] == "failed"


def test_cards_show_the_words_an_act_will_keep(client, with_issue, new_agent):  # noqa: F811
    agent_id = with_issue()
    report = {
        "title": "Books under the parent's name",
        "description": "The clinic emailed: a mother booked for her son, in her own name.",
        "step": None,
        "severity": "booking",
        "reported": "clinic",
        "calls": [],
    }
    card = tools.TOOLS["open_issue"].card(agent_id, report)
    assert card["stored"] == [report["description"]]

    other, _ = new_agent("Other")
    test = {"pull": 1, "name": "Books for a child", "caller": "Ana books for Leo.",
            "checks": ["Records Leo as the patient", "Ends the call"]}  # fmt: skip
    card = tools.TOOLS["add_test"].card(other, test)
    assert card["stored"] == [
        "Caller: Ana books for Leo.",
        "Check: Records Leo as the patient",
        "Check: Ends the call",
    ]


def test_a_card_left_running_by_a_stopped_server_is_failed_at_startup(
    client,
    with_issue,  # noqa: F811
    prosper_model,
):
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")
    index = len(chat["messages"]) - 1
    store.chats.claim_action(agent_id, chat["id"], index, True)  # and the server stops

    store.init_db()

    action = store.chats.get_chat(agent_id, chat["id"])["messages"][index]["action"]
    assert (action["state"], action["error"]) == ("failed", store.chats.INTERRUPTED)


def test_flaky_tests_are_said_as_flaky_not_as_failing(client, new_agent, verdicts):  # noqa: F811
    agent_id, _ = new_agent()
    test = {"name": "Is polite", "caller": "Ana books.", "checks": ["Is polite"]}
    client.post(f"/api/agents/{agent_id}/pulls/1/tests", json=test)
    verdicts += [False]  # one of its three calls fails: 2/3
    settle()

    output, _ = tools.TOOLS["read_tests"].read(agent_id, {"pull": 1})
    assert "- Is polite · flaky, 2/3" in output
    assert "is flaky one short of it (shown, and does not block a merge)" in output
    assert "Now: 0 of 1 pass, 1 flaky (2/3: does not block a merge)." in output
    listed, _ = tools.TOOLS["list_pulls"].read(agent_id, {"state": None})
    assert "checks passed: 0 of 1 pass, 1 flaky (2/3: does not block a merge)" in listed


def test_a_waiting_card_survives_a_restart_and_do_it_still_works(
    client,
    with_issue,  # noqa: F811
    prosper_model,
):
    agent_id = with_issue()
    prosper_model.script = {"ask": [tool("read_issue", number=ISSUE), SNOOZE]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")
    index = len(chat["messages"]) - 1
    # The run is kept with the card, as JSON in the chat's row: nothing in memory.
    with store.db.connect() as conn:
        (row,) = conn.execute("SELECT messages FROM chats WHERE id = ?", (chat["id"],)).fetchone()
    assert json.loads(row)[index]["resume"]["state"]["current_turn"] == 2

    # The server restarts: startup runs, and a new model answers what comes next.
    store.init_db()
    assert _state(client, agent_id) == "open"
    prosper_model.script = {"ask": [{"answer": "It comes back next week.", "links": []}]}
    chat = _decide(client, agent_id, chat, index)

    assert _state(client, agent_id) == "snoozed"
    assert chat["messages"][index]["action"]["state"] == "done"
    assert chat["messages"][-1]["text"] == "It comes back next week."
    # It went on from the run as it was: the read, the call, then the act's result.
    resumed = prosper_model.asked["ask"][-1]
    types = [item.get("type") for item in resumed[2:]]
    assert types == ["function_call", "function_call_output"] * 2
    assert resumed[-1]["output"] == "Snoozed Issue #2"


def test_a_card_kept_before_runs_were_kept_is_still_done(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [SNOOZE]}
    chat = _ask(client, agent_id, "Snooze Issue #2 for a week.")
    index = len(chat["messages"]) - 1
    # As an older server kept it: the conversation's items, not the run.
    with store.db.connect() as conn:
        messages = json.loads(
            conn.execute("SELECT messages FROM chats WHERE id = ?", (chat["id"],)).fetchone()[0]
        )
        messages[index]["resume"] = {"items": [], "call": "call_1", "used": 1}
        conn.execute(
            "UPDATE chats SET messages = ? WHERE id = ?", (json.dumps(messages), chat["id"])
        )
    asked = len(prosper_model.asked["ask"])

    chat = _decide(client, agent_id, chat, index)

    assert _state(client, agent_id) == "snoozed"
    assert chat["messages"][index]["action"]["result"]["text"] == "Snoozed Issue #2"
    assert len(prosper_model.asked["ask"]) == asked  # done, with nothing to go on from


def test_every_request_is_counted_and_nothing_is_traced(client, with_issue, prosper_model):  # noqa: F811
    agent_id = with_issue()
    prosper_model.script = {"ask": [tool("list_versions"), ANSWER]}
    prosper_model.usage["requests"] = 0  # what the calls' reviews asked, before

    chat = _ask(client, agent_id, "Which versions are there?")

    assert chat["usage"]["requests"] == 2
    assert agent._RUN.tracing_disabled
    assert agents.tracing.get_trace_provider()._manual_disabled
