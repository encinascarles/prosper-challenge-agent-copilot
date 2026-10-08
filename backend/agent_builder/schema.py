#
# Agent schema — the declarative contract the Phase 2 Copilot reads and writes.
#
# Design rule: stay as close to Pipecat Flows' own vocabulary as possible. A node
# carries Pipecat's native fields (`role_message`, `task_messages`, `pre/post_actions`)
# verbatim. The ONLY thing we add is `edges`: transitions expressed as DATA (a string
# `target`) rather than as Python closures — because a Copilot can emit a string, not
# a callable. `AgentBuilder` turns these strings back into the closures Pipecat wants.
#
# `from_dict` checks the shape as it reads: a missing field or a wrong type raises a
# ValueError that says where, because agents arrive from the API and the Copilot, and
# "KeyError: 'name'" does not tell either of them what to fix.
#

from dataclasses import dataclass, field
from typing import Optional

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # ElevenLabs "Rachel"
DEFAULT_MODEL = "gpt-4o"

class AgentError(ValueError):
    """What is wrong with an agent, and where: the node and the edge, by name.

    The sentence is for a person. The names are for a program (the editor marks
    the card), so it does not have to read them back out of the sentence. `edge`
    is the edge's function name, which is what identifies it within its node.
    """

    def __init__(self, message: str, node: Optional[str] = None, edge: Optional[str] = None):
        super().__init__(message)
        self.node = node
        self.edge = edge


def _located(error: ValueError, node: Optional[str] = None, edge: Optional[str] = None):
    """`error` as an AgentError that also says where, keeping what it already knew."""
    return AgentError(
        str(error),
        node=node or getattr(error, "node", None),
        edge=edge or getattr(error, "edge", None),
    )


_MISSING = object()
# Named as JSON names them: the reader of the message wrote JSON, not Python.
_JSON_NAMES = {
    dict: "an object",
    list: "a list",
    str: "a string",
    bool: "true or false",
    int: "a number",
    float: "a number",
    type(None): "null",
}


def _json_name(value) -> str:
    return _JSON_NAMES.get(type(value), type(value).__name__)


def _as_object(value, where: str) -> dict:
    if not isinstance(value, dict):
        subject = where[0].upper() + where[1:]
        raise ValueError(f"{subject} must be an object, got {_json_name(value)}.")
    return value


def _read(d: dict, key: str, kind: type, where: str, default=_MISSING, items: type = None):
    """Field `key` of `d`, checked to be a `kind` (and, for a list, a list of `items`).

    Without a `default` the field is required. A `None` default also accepts null.
    """
    if key not in d:
        if default is _MISSING:
            raise ValueError(f"Missing required field '{key}' in {where}.")
        return default
    value = d[key]
    if value is None and default is None:
        return None
    if not isinstance(value, kind):
        raise ValueError(
            f"'{key}' in {where} must be {_JSON_NAMES[kind]}, got {_json_name(value)}."
        )
    if items and not all(isinstance(item, items) for item in value):
        raise ValueError(f"Every item of '{key}' in {where} must be {_JSON_NAMES[items]}.")
    return value


@dataclass
class Edge:
    """A transition out of a node, exposed to the LLM as a callable tool."""

    function: str            # tool name the LLM calls to take this edge
    description: str         # when the model should call it
    target: str              # node to transition to (by name)
    # Fields to collect on this edge, as JSON-schema properties.
    properties: dict = field(default_factory=dict)
    required: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, where: str = "the edge", node: str = "") -> "Edge":
        # `node` is the owning node as the messages name it ("node 'greeting'").
        of_node = f" of {node}" if node else ""
        d = _as_object(d, where + of_node)
        function = _read(d, "function", str, where + of_node)
        where = f"edge '{function}'{of_node}"
        try:
            return cls(
                function=function,
                description=_read(d, "description", str, where),
                target=_read(d, "target", str, where),
                properties=_read(d, "properties", dict, where, default={}),
                required=_read(d, "required", list, where, default=[], items=str),
            )
        except ValueError as error:
            raise _located(error, edge=function) from error


@dataclass
class Node:
    """A single conversational state. Fields mirror Pipecat Flows' NodeConfig."""

    name: str
    task_messages: list = field(default_factory=list)   # this node's objectives
    role_message: Optional[str] = None                  # overrides the global persona
    edges: list = field(default_factory=list)           # list[Edge]; transitions out
    pre_actions: list = field(default_factory=list)
    post_actions: list = field(default_factory=list)
    end: bool = False                                   # terminal -> ends the call

    @classmethod
    def from_dict(cls, d: dict, where: str = "the node") -> "Node":
        d = _as_object(d, where)
        name = _read(d, "name", str, where)
        try:
            return cls._named(d, name)
        except ValueError as error:
            raise _located(error, node=name) from error

    @classmethod
    def _named(cls, d: dict, name: str) -> "Node":
        where = f"node '{name}'"
        edges = _read(d, "edges", list, where, default=[])
        task_messages = _read(d, "task_messages", list, where, default=[], items=dict)
        # Messages and actions go to the LLM and to Flows as they are, so the
        # fields those read are checked here. An action's `type` is only checked
        # to be there: Flows lets a bot register its own action types.
        for i, message in enumerate(task_messages, start=1):
            _read(message, "role", str, f"task message {i} of {where}")
            _read(message, "content", str, f"task message {i} of {where}")
        actions = {}
        for key, label in (("pre_actions", "pre-action"), ("post_actions", "post-action")):
            actions[key] = _read(d, key, list, where, default=[], items=dict)
            for i, action in enumerate(actions[key], start=1):
                _read(action, "type", str, f"{label} {i} of {where}")
        return cls(
            name=name,
            task_messages=task_messages,
            role_message=_read(d, "role_message", str, where, default=None),
            edges=[Edge.from_dict(e, f"edge {i}", where) for i, e in enumerate(edges, start=1)],
            pre_actions=actions["pre_actions"],
            post_actions=actions["post_actions"],
            end=_read(d, "end", bool, where, default=False),
        )


@dataclass
class AgentConfig:
    """A complete agent: identity + the conversation graph."""

    name: str
    initial_node: str
    nodes: list                          # list[Node]
    persona: str = ""                    # global role_message, applied to every node
    voice_id: str = DEFAULT_VOICE_ID
    model: str = DEFAULT_MODEL

    @classmethod
    def from_dict(cls, d: dict) -> "AgentConfig":
        where = "the agent"
        d = _as_object(d, where)
        nodes = _read(d, "nodes", list, where)
        return cls(
            name=_read(d, "name", str, where),
            initial_node=_read(d, "initial_node", str, where),
            nodes=[Node.from_dict(n, f"node {i}") for i, n in enumerate(nodes, start=1)],
            persona=_read(d, "persona", str, where, default=""),
            voice_id=_read(d, "voice_id", str, where, default=DEFAULT_VOICE_ID),
            model=_read(d, "model", str, where, default=DEFAULT_MODEL),
        )
