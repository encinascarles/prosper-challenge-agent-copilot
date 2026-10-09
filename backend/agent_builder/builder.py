#
# AgentBuilder — loads a declarative agent (JSON / dict) and compiles its node
# graph into Pipecat Flows objects.
#
#   JSON  ->  AgentConfig (validated)  ->  Pipecat Flows NodeConfig graph
#
# This is the seam between "agent as data" (what the Phase 2 Copilot produces)
# and "agent as a running conversation" (what bot.py executes). Keeping the
# compile + validation here means bot.py never touches the graph internals.
#
# Every compiled node opens with a `node_entered` pre-action saying where the call is and
# how it got there. Flows runs a node's pre-actions each time the node is
# entered, the first one included, so that is the one place every transition
# goes through. The builder only states the fact and logs it; whoever runs the
# graph decides what else to do with it by registering its own handler,
# `flow_manager.register_action(NODE_ACTION, ...)`, which Flows then uses instead.
# The type is reserved (schema.py refuses it in an agent's own actions), so the
# handler only ever sees the builder's.
#

import json
import re
from pathlib import Path
from typing import Optional, Union

from loguru import logger
from pipecat_flows import FlowManager, FlowsFunctionSchema, NodeConfig

from .schema import NODE_ACTION, AgentConfig, AgentError, Edge, Node

# What the LLM APIs accept as a tool name. An edge's function is sent as one.
_TOOL_NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}")



async def _log_node(action: dict, flow_manager: FlowManager) -> None:
    # The handler for a runner that registered none: Flows refuses a node whose
    # action type has no handler, so the graph runs anywhere without one.
    logger.info(f"Entered node '{action['node']}' from {action['from']} via {action['edge']}")


class AgentBuilder:
    """Builds a runnable Pipecat Flows graph from a declarative AgentConfig."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._nodes_by_name = {n.name: n for n in config.nodes}
        self._validate()

    # ---- loading -----------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict) -> "AgentBuilder":
        return cls(AgentConfig.from_dict(data))

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "AgentBuilder":
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data)

    # ---- validation --------------------------------------------------------
    def _validate(self) -> None:
        if not self.config.nodes:
            raise ValueError("Agent has no nodes.")
        # Nodes are looked up by name on every transition: with a duplicate, one
        # of the two silently never runs.
        seen = set()
        for node in self.config.nodes:
            if node.name in seen:
                raise AgentError(
                    f"Two nodes are named '{node.name}'. Node names must be unique.",
                    node=node.name,
                )
            seen.add(node.name)
        names = set(self._nodes_by_name)
        if self.config.initial_node not in names:
            raise ValueError(
                f"initial_node '{self.config.initial_node}' is not a defined node."
            )
        for node in self.config.nodes:
            # A node's edges become the tools of one LLM request, which the
            # provider rejects mid-call if a name is invalid or repeated.
            functions = set()
            for edge in node.edges:
                if not _TOOL_NAME.fullmatch(edge.function):
                    raise AgentError(
                        f"Edge function '{edge.function}' in node '{node.name}' is not a valid "
                        "tool name: use 1 to 64 letters, digits, underscores or hyphens.",
                        node=node.name,
                        edge=edge.function,
                    )
                if edge.function in functions:
                    raise AgentError(
                        f"Node '{node.name}' has two edges with the function "
                        f"'{edge.function}'. Functions must be unique within a node.",
                        node=node.name,
                        edge=edge.function,
                    )
                functions.add(edge.function)
                if edge.target not in names:
                    raise AgentError(
                        f"Edge '{edge.function}' in node '{node.name}' targets "
                        f"unknown node '{edge.target}'.",
                        node=node.name,
                        edge=edge.function,
                    )

    # ---- compilation -------------------------------------------------------
    def build_initial_node(self) -> NodeConfig:
        """Return the entry NodeConfig; downstream nodes are built lazily on transition."""
        return self._make_node(self._nodes_by_name[self.config.initial_node])

    def _make_node(
        self,
        node: Node,
        came_from: Optional[str] = None,
        via: Optional[str] = None,
        collected: Optional[dict] = None,
    ) -> NodeConfig:
        # Where the call is now and what brought it here: the node it left, the
        # edge function the model called and the arguments it passed. The start
        # node has none of the three.
        entered = {
            "type": NODE_ACTION,
            "node": node.name,
            "from": came_from,
            "edge": via,
            "collected": collected or {},
            "handler": _log_node,
        }
        node_config: NodeConfig = {
            "name": node.name,
            "role_message": node.role_message or self.config.persona,
            "task_messages": node.task_messages,
            "functions": [self._make_edge_function(node, edge) for edge in node.edges],
            # First, so the node is reported before any of its own pre-actions
            # speaks.
            "pre_actions": [entered, *node.pre_actions],
        }
        # Explicit post_actions win; otherwise a terminal node ends the call.
        if node.post_actions:
            node_config["post_actions"] = node.post_actions
        elif node.end:
            node_config["post_actions"] = [{"type": "end_conversation"}]
        return node_config

    def _make_edge_function(self, node: Node, edge: Edge) -> FlowsFunctionSchema:
        async def handler(args: dict, flow_manager: FlowManager):
            # Persist what the caller gave us so later nodes can use it.
            flow_manager.state.update(args)
            logger.info(f"[{edge.function}] -> {edge.target} | collected: {args}")
            next_node = self._make_node(
                self._nodes_by_name[edge.target],
                came_from=node.name,
                via=edge.function,
                collected=dict(args),
            )
            return {"status": "success", **args}, next_node

        return FlowsFunctionSchema(
            name=edge.function,
            description=edge.description,
            properties=edge.properties,
            required=edge.required,
            handler=handler,
        )
