#
# What AgentBuilder refuses, and what it says when it does.
#
# The messages are part of the contract: the API returns them as they are, the
# editor shows them and the Copilot will read them to repair a graph. So each
# case pins the sentence, not only the fact that something was raised.
#

import copy

import pytest

from agent_builder import AgentBuilder


def _drop(*path):
    """A change that removes the field at `path` (keys and list indexes)."""

    def change(agent):
        *parents, last = path
        target = agent
        for step in parents:
            target = target[step]
        del target[last]

    return change


def _set(*path, value):
    """A change that sets the field at `path` to `value`."""

    def change(agent):
        *parents, last = path
        target = agent
        for step in parents:
            target = target[step]
        target[last] = value

    return change


def _repeat(*path):
    """A change that appends a copy of the first item of the list at `path`."""

    def change(agent):
        target = agent
        for step in path:
            target = target[step]
        target.append(copy.deepcopy(target[0]))

    return change


FIRST_EDGE = ("nodes", 0, "edges", 0)

MALFORMED = {
    # ---- missing required fields, at each level ----
    "agent without name": (_drop("name"), "Missing required field 'name' in the agent."),
    "agent without initial_node": (
        _drop("initial_node"),
        "Missing required field 'initial_node' in the agent.",
    ),
    "agent without nodes": (_drop("nodes"), "Missing required field 'nodes' in the agent."),
    "node without name": (_drop("nodes", 1, "name"), "Missing required field 'name' in node 2."),
    "edge without function": (
        _drop(*FIRST_EDGE, "function"),
        "Missing required field 'function' in edge 1 of node 'greeting'.",
    ),
    "edge without description": (
        _drop(*FIRST_EDGE, "description"),
        "Missing required field 'description' in edge 'choose_intent' of node 'greeting'.",
    ),
    "edge without target": (
        _drop(*FIRST_EDGE, "target"),
        "Missing required field 'target' in edge 'choose_intent' of node 'greeting'.",
    ),
    # ---- wrong types ----
    "name is null": (
        _set("name", value=None),
        "'name' in the agent must be a string, got null.",
    ),
    "model is a number": (
        _set("model", value=4),
        "'model' in the agent must be a string, got a number.",
    ),
    "nodes is a number": (
        _set("nodes", value=5),
        "'nodes' in the agent must be a list, got a number.",
    ),
    "node is a string": (
        _set("nodes", 1, value="x"),
        "Node 2 must be an object, got a string.",
    ),
    "task_messages is a string": (
        _set("nodes", 0, "task_messages", value="hi"),
        "'task_messages' in node 'greeting' must be a list, got a string.",
    ),
    "task_messages holds strings": (
        _set("nodes", 0, "task_messages", value=["hi"]),
        "Every item of 'task_messages' in node 'greeting' must be an object.",
    ),
    "task message without role": (
        _drop("nodes", 0, "task_messages", 0, "role"),
        "Missing required field 'role' in task message 1 of node 'greeting'.",
    ),
    "task message without content": (
        _drop("nodes", 0, "task_messages", 0, "content"),
        "Missing required field 'content' in task message 1 of node 'greeting'.",
    ),
    "task message role is a number": (
        _set("nodes", 0, "task_messages", 0, "role", value=1),
        "'role' in task message 1 of node 'greeting' must be a string, got a number.",
    ),
    "task message content is a list": (
        _set("nodes", 0, "task_messages", 0, "content", value=["Greet the caller."]),
        "'content' in task message 1 of node 'greeting' must be a string, got a list.",
    ),
    "pre-action without type": (
        _set("nodes", 0, "pre_actions", value=[{"type": "tts_say", "text": "Hi"}, {"text": "Hi"}]),
        "Missing required field 'type' in pre-action 2 of node 'greeting'.",
    ),
    "pre-action type is a number": (
        _set("nodes", 0, "pre_actions", value=[{"type": 1}]),
        "'type' in pre-action 1 of node 'greeting' must be a string, got a number.",
    ),
    "post-action without type": (
        _set("nodes", 0, "post_actions", value=[{"text": "Bye"}]),
        "Missing required field 'type' in post-action 1 of node 'greeting'.",
    ),
    "post-action type is null": (
        _set("nodes", 0, "post_actions", value=[{"type": None}]),
        "'type' in post-action 1 of node 'greeting' must be a string, got null.",
    ),
    "pre-action of the reserved type": (
        _set("nodes", 0, "pre_actions", value=[{"type": "node_entered"}]),
        "Pre-action 1 of node 'greeting' has the type 'node_entered', which is reserved: "
        "every node already starts with one, to report where the call is.",
    ),
    "post-action of the reserved type": (
        _set("nodes", 0, "post_actions", value=[{"type": "node_entered"}]),
        "Post-action 1 of node 'greeting' has the type 'node_entered', which is reserved: "
        "every node already starts with one, to report where the call is.",
    ),
    "pre_actions holds strings": (
        _set("nodes", 0, "pre_actions", value=["tts_say"]),
        "Every item of 'pre_actions' in node 'greeting' must be an object.",
    ),
    "end is a string": (
        _set("nodes", 0, "end", value="yes"),
        "'end' in node 'greeting' must be true or false, got a string.",
    ),
    "edge is a number": (
        _set("nodes", 0, "edges", value=[3]),
        "Edge 1 of node 'greeting' must be an object, got a number.",
    ),
    "properties is a list": (
        _set(*FIRST_EDGE, "properties", value=[]),
        "'properties' in edge 'choose_intent' of node 'greeting' must be an object, got a list.",
    ),
    "required holds numbers": (
        _set(*FIRST_EDGE, "required", value=[1]),
        "Every item of 'required' in edge 'choose_intent' of node 'greeting' must be a string.",
    ),
    # ---- a well-formed document that is not a runnable graph ----
    "no nodes": (_set("nodes", value=[]), "Agent has no nodes."),
    "unknown initial_node": (
        _set("initial_node", value="nowhere"),
        "initial_node 'nowhere' is not a defined node.",
    ),
    "edge to an unknown node": (
        _set(*FIRST_EDGE, "target", value="x"),
        "Edge 'choose_intent' in node 'greeting' targets unknown node 'x'.",
    ),
    "two nodes with the same name": (
        _repeat("nodes"),
        "Two nodes are named 'greeting'. Node names must be unique.",
    ),
    "two edges with the same function": (
        _repeat("nodes", 0, "edges"),
        "Node 'greeting' has two edges with the function 'choose_intent'. "
        "Functions must be unique within a node.",
    ),
    "function with a space": (
        _set(*FIRST_EDGE, "function", value="choose intent"),
        "Edge function 'choose intent' in node 'greeting' is not a valid tool name: "
        "use 1 to 64 letters, digits, underscores or hyphens.",
    ),
    "function too long": (
        _set(*FIRST_EDGE, "function", value="f" * 65),
        f"Edge function '{'f' * 65}' in node 'greeting' is not a valid tool name: "
        "use 1 to 64 letters, digits, underscores or hyphens.",
    ),
}


def test_the_example_agent_builds(agent):
    builder = AgentBuilder.from_dict(agent)

    assert builder.build_initial_node()["name"] == "greeting"


@pytest.mark.parametrize("change, message", MALFORMED.values(), ids=MALFORMED.keys())
def test_malformed_agent_is_refused_with_a_located_message(agent, change, message):
    change(agent)

    # ValueError and nothing else: the API maps it to a 422, anything else
    # would surface as a 500.
    with pytest.raises(ValueError) as error:
        AgentBuilder.from_dict(agent)
    assert str(error.value) == message


def test_a_body_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError, match="The agent must be an object, got a list."):
        AgentBuilder.from_dict([])


def test_optional_fields_fall_back_to_defaults(agent):
    for field in ("persona", "voice_id", "model"):
        del agent[field]
    agent["nodes"][0]["role_message"] = None  # null means "use the persona"

    config = AgentBuilder.from_dict(agent).config

    assert (config.persona, config.model) == ("", "gpt-4o")
    assert config.nodes[0].role_message is None


def test_the_same_function_may_repeat_in_different_nodes(agent):
    # Uniqueness is per node: each node sends its own tool list.
    agent["nodes"][1]["edges"][0]["function"] = agent["nodes"][0]["edges"][0]["function"]

    AgentBuilder.from_dict(agent)


def test_any_action_type_is_accepted(agent):
    # Not checked against a list: Flows lets a bot register its own action types.
    agent["nodes"][0]["pre_actions"] = [{"type": "tts_say", "text": "One moment."}]
    agent["nodes"][0]["post_actions"] = [{"type": "notify_front_desk", "channel": "sms"}]

    node = AgentBuilder.from_dict(agent).config.nodes[0]

    assert [a["type"] for a in node.pre_actions + node.post_actions] == [
        "tts_say",
        "notify_front_desk",
    ]
