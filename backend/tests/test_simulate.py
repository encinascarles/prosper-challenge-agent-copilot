#
# Simulated calls, run on the real pipeline with a scripted LLM: where a turn
# ends, the path the call takes, how checks are read and decided, and a suite
# run end to end. Nothing here reaches OpenAI.
#

import asyncio

import pytest

from agent_builder import AgentBuilder
from simulate import parse, run_suite
from simulate.checks import decide
from simulate.text_call import TextCall
from tests.fakes import (
    BOOKING,
    BOOKING_CALLER,
    FakeServices,
    ScriptedCaller,
    ScriptedLLM,
    call,
    say,
)


def _run(agent: dict, script: list, lines: list[str]) -> tuple[dict, ScriptedCaller]:
    caller = ScriptedCaller(lines)
    result = asyncio.run(TextCall(AgentBuilder.from_dict(agent), ScriptedLLM(script)).run(caller))
    return result, caller


def test_a_call_follows_the_graph_to_its_end_and_reports_the_path(agent):
    result, _ = _run(agent, BOOKING, BOOKING_CALLER)

    assert result["ended"] == "agent_ended"
    assert [step["node"] for step in result["path"]] == [
        "greeting",
        "collect_details",
        "offer_times",
        "confirm",
    ]
    assert result["path"][2] == {
        "node": "offer_times",
        "from": "collect_details",
        "edge": "record_details",
        "collected": {"full_name": "Maria Lopez", "reason": "check-up"},
    }
    assert result["tokens"] == {"prompt": 70, "completion": 35}


def test_the_agents_turn_ends_only_at_a_response_that_calls_no_function(agent):
    # Each caller line is answered by a function call and then by words: the
    # caller must be asked only after the words, never after the call alone.
    result, caller = _run(agent, BOOKING, BOOKING_CALLER)

    assert [len(heard) for heard in caller.heard] == [1, 3, 5]
    assert [line["role"] for line in result["transcript"]] == ["agent", "caller"] * 3 + ["agent"]
    # Each line is said where it was said: the reply after a transition, in the new step.
    assert [line["node"] for line in result["transcript"] if line["role"] == "agent"] == [
        "greeting",
        "collect_details",
        "offer_times",
        "confirm",
    ]


def test_transitions_without_words_are_one_turn(agent):
    # The caller says everything at once: the agent moves through two steps
    # before it says anything, and that is still one turn.
    script = [
        say("Hi, how can I help?"),
        call("choose_intent", intent="book"),
        call("record_details", full_name="John Smith", reason="cleaning"),
        say("Tuesday at 10 AM or Thursday at 2 PM?"),
    ]
    result, caller = _run(agent, script, ["Book a cleaning for John Smith."])

    assert [len(heard) for heard in caller.heard] == [1, 3]
    assert result["ended"] == "caller_hung_up"
    assert [step["node"] for step in result["path"]][-1] == "offer_times"


def test_a_call_that_goes_on_is_cut_at_the_turn_cap(agent):
    script = [say("Hi, how can I help?")] + [say("Sorry, could you repeat that?")] * 3
    caller = ScriptedCaller(["Hm?"] * 5)
    builder = AgentBuilder.from_dict(agent)

    result = asyncio.run(TextCall(builder, ScriptedLLM(script)).run(caller, max_turns=3))

    assert result["ended"] == "turn_cap"
    assert len(caller.heard) == 3


@pytest.mark.parametrize(
    "line, check",
    [
        ("Reaches Confirm", {"kind": "reaches", "name": "Confirm"}),
        ("reaches the offer times step.", {"kind": "reaches", "name": "offer times"}),
        ("Ends the call", {"kind": "ends"}),
        ("The agent ends the call.", {"kind": "ends"}),
        ("Full name is recorded", {"kind": "recorded", "name": "Full name"}),
        ("Never gives medical advice", {"kind": "judged"}),
        ("Confirms the time before ending the call", {"kind": "judged"}),
    ],
)
def test_a_check_line_is_read_into_its_kind(line, check):
    assert parse(line) == {"text": line, **check}


def test_path_checks_are_decided_from_the_path(agent):
    result, _ = _run(agent, BOOKING, BOOKING_CALLER)

    def check(line):
        return decide(parse(line), result)

    assert check("Reaches offer times") == {"pass": True, "detail": None}
    assert check("Ends the call") == {"pass": True, "detail": None}
    assert check("Full name is recorded") == {"pass": True, "detail": "full_name: Maria Lopez"}
    assert check("Date of birth is recorded") == {"pass": False, "detail": "Never recorded."}
    assert check("Never gives medical advice") is None


def test_a_call_that_did_not_reach_a_step_says_where_it_went(agent):
    result, _ = _run(agent, BOOKING[:3], ["I want to cancel."])

    assert decide(parse("Reaches Confirm"), result) == {
        "pass": False,
        "detail": "Never got there: greeting → collect_details.",
    }
    assert decide(parse("Ends the call"), result) == {
        "pass": False,
        "detail": "The caller hung up; the agent never ended the call.",
    }


def test_a_suite_runs_each_test_three_times_and_judges_what_the_path_cannot(agent):
    services = FakeServices(verdict=False)
    tests = [
        {"id": "t1", "name": "Books", "caller": "Maria", "checks": ["Reaches Confirm"]},
        {"id": "t2", "name": "Polite", "caller": "Maria", "checks": ["Ends the call", "Is polite"]},
    ]
    results = []

    asyncio.run(run_suite(agent, [], tests, lambda t, r: results.append((t["id"], r)), services))

    assert sorted(test for test, _ in results) == ["t1"] * 3 + ["t2"] * 3
    books = next(result for test, result in results if test == "t1")
    assert books["passed"] is True
    assert books["checks"] == [
        {"text": "Reaches Confirm", "kind": "reaches", "pass": True, "detail": None}
    ]
    polite = next(result for test, result in results if test == "t2")
    assert polite["passed"] is False
    assert polite["checks"][1] == {
        "text": "Is polite",
        "kind": "judged",
        "pass": False,
        "detail": "Judged on 7 lines.",
    }
    assert polite["tokens"]["judge"] == {"prompt": 7, "completion": 3}
    assert services.judged == ["Is polite"] * 3


class NoLLM(FakeServices):
    def llm(self, model):
        raise RuntimeError("The OpenAI key is missing.")


def test_a_call_that_breaks_fails_its_checks_instead_of_the_suite(agent):
    services = NoLLM()
    tests = [{"id": "t", "name": "Books", "caller": "Maria", "checks": ["Reaches Confirm"]}]
    results = []

    asyncio.run(run_suite(agent, [], tests, lambda t, r: results.append(r), services, repeats=1))

    (result,) = results
    assert result["ended"] == "error"
    assert result["checks"] == [
        {
            "text": "Reaches Confirm",
            "kind": "reaches",
            "pass": False,
            "detail": "The call did not run: The OpenAI key is missing.",
        }
    ]
    assert result["passed"] is False
