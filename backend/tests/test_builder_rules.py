#
# Rules reach the prompt when the graph is built, and only there: the agent
# JSON stays as it was written.
#

import copy

import pytest

from agent_builder import AgentBuilder
from agent_builder.builder import STEP_GUIDE

EVERY = {"step": None, "text": "Never give medical advice."}
CONFIRM = {"step": "confirm", "text": "Read the date back before saying goodbye."}


def _node(builder: AgentBuilder, name: str) -> dict:
    return builder._make_node(builder._nodes_by_name[name])


def test_rules_for_every_step_end_each_nodes_role_message(agent):
    builder = AgentBuilder.from_dict(agent, [EVERY])

    for name in ("greeting", "confirm"):
        role = _node(builder, name)["role_message"]
        assert role.startswith(agent["persona"])
        assert role.endswith(
            "Always follow these rules, on every step of the call:\n- Never give medical advice."
        )


def test_a_steps_rules_are_one_more_task_message_of_that_step_only(agent):
    builder = AgentBuilder.from_dict(agent, [CONFIRM])

    confirm = _node(builder, "confirm")["task_messages"]
    assert confirm[:-1] == agent["nodes"][-1]["task_messages"]
    assert confirm[-1] == {
        "role": "developer",
        "content": "Rules for this step:\n- Read the date back before saying goodbye.",
    }
    greeting = _node(builder, "greeting")["task_messages"]
    assert greeting == [
        *agent["nodes"][0]["task_messages"],
        {"role": "developer", "content": STEP_GUIDE},
    ]
    assert _node(builder, "greeting")["role_message"] == agent["persona"]


def test_a_step_that_moves_on_is_told_to_call_its_functions(agent):
    builder = AgentBuilder.from_dict(agent)

    assert _node(builder, "greeting")["task_messages"][-1]["content"] == STEP_GUIDE
    # The step that ends the call has no function to call.
    assert _node(builder, "confirm")["task_messages"] == agent["nodes"][-1]["task_messages"]


def test_rules_leave_the_agent_json_untouched(agent):
    before = copy.deepcopy(agent)

    builder = AgentBuilder.from_dict(agent, [EVERY, CONFIRM])
    _node(builder, "confirm")

    assert agent == before


def test_a_rule_for_a_step_that_is_not_a_node_is_refused(agent):
    with pytest.raises(ValueError, match="Rule 1 is for step 'nowhere', which is not a node."):
        AgentBuilder.from_dict(agent, [{"step": "nowhere", "text": "Hi."}])
