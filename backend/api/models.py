#
# What the builder's routes share: the body that saves an agent, the shape of
# their errors, and the check that makes a config an agent.
#

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_builder import AgentBuilder

# There are no accounts: whoever uses the builder is "you" in a pull request's
# log. Prosper's own changes will be logged under its name.
YOU = "you"

# The sample agent doubles as the request example in the OpenAPI docs.
EXAMPLE_AGENT = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())


class Position(BaseModel):
    x: float
    y: float


class AgentSave(BaseModel):
    config: dict[str, Any] = Field(
        description="The agent JSON: name, initial_node and nodes, each node with its edges.",
        examples=[EXAMPLE_AGENT],
    )
    # Optional so a client that only changes the agent (the Copilot proposing a
    # fix) does not have to read the positions first to send them back.
    layout: dict[str, Position] | None = Field(
        default=None,
        description=(
            "Node positions by node name. Omit to keep the stored ones (none, for a "
            "new agent). Positions for names that are not nodes of the agent are dropped."
        ),
        examples=[{"greeting": {"x": 0, "y": 0}}],
    )

    def positions(self) -> dict[str, dict] | None:
        """The layout as the plain dict the store writes, or None if it was left out."""
        if self.layout is None:
            return None
        return {name: position.model_dump() for name, position in self.layout.items()}


class Problem(BaseModel):
    detail: str  # one sentence naming what is wrong


class InvalidAgent(Problem):
    # Where the problem is, when it is in one place, so a client can point at
    # it without reading the names back out of the sentence.
    node: str | None = None  # the node's name
    edge: str | None = None  # the edge's function, within that node


NOT_FOUND = {404: {"model": Problem, "description": "No agent has this id."}}
INVALID = {
    422: {
        "model": InvalidAgent,
        "description": "The agent is not valid; says why, and which node and edge.",
    }
}


def problem(config: dict) -> JSONResponse | None:
    """The 422 that says why `config` is not an agent the bot could run, or None if it is."""
    try:
        AgentBuilder.from_dict(config)
        return None
    except ValueError as error:
        found = {"detail": str(error)}
        # Only the fields that apply: a problem with the agent as a whole
        # (no nodes, no start) names neither.
        for field in ("node", "edge"):
            if getattr(error, field, None) is not None:
                found[field] = getattr(error, field)
    except (KeyError, TypeError) as error:
        # agent_builder reports problems as ValueError. This is the net under
        # it: a shape it did not foresee is still the client's 422, not a 500.
        reason = (
            f"missing field {error}" if isinstance(error, KeyError) else f"wrong type ({error})"
        )
        found = {"detail": f"Invalid agent: {reason}."}
    return JSONResponse(status_code=422, content=found)


def not_found(agent_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No agent with id '{agent_id}'.")
