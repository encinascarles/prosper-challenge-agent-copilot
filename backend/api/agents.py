#
# Agents API — the routes the graph editor uses to list, open, create and
# save agents.
#
# Thin on purpose: HTTP in, validate, store call, HTTP out. Persistence lives
# in `store`, the agent contract in `agent_builder`.
#
# An agent is accepted only if AgentBuilder accepts it: every agent saved
# through here has passed the same validation the builder runs before a call.
# That covers the shape of the document and the graph (names, targets, tool
# names), not how the conversation goes. It is also why the request body is a
# plain JSON object and not a Pydantic model of the agent: schema.py already
# defines it, and a second definition would drift.
#
# Saving takes the node positions next to the agent, never inside it: the agent
# JSON stays what Pipecat runs, and both are written together so a reload shows
# the graph as it was left.
#
# Handlers are plain `def`: sqlite3 blocks, and FastAPI runs sync handlers in a
# thread pool, which keeps them off the event loop the voice pipeline runs on.
#

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import store
from agent_builder import AgentBuilder

router = APIRouter(prefix="/api/agents", tags=["agents"])

# The sample agent doubles as the request example in the OpenAPI docs.
_EXAMPLE_AGENT = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())


class AgentSummary(BaseModel):
    id: str
    name: str
    nodes: int  # how many nodes the graph has
    updated_at: str


class Position(BaseModel):
    x: float
    y: float


class AgentRecord(BaseModel):
    id: str
    config: dict[str, Any]  # the agent JSON, as agent_builder/schema.py defines it
    layout: dict[str, Position]  # where the editor drew each node, by node name
    created_at: str
    updated_at: str


class AgentSave(BaseModel):
    config: dict[str, Any] = Field(
        description="The agent JSON: name, initial_node and nodes, each node with its edges.",
        examples=[_EXAMPLE_AGENT],
    )
    # Optional so a client that only changes the agent (the Copilot applying a
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


_NOT_FOUND = {404: {"model": Problem, "description": "No agent has this id."}}
_INVALID = {
    422: {
        "model": InvalidAgent,
        "description": "The agent is not valid; says why, and which node and edge.",
    }
}


def _problem(config: dict) -> JSONResponse | None:
    """The 422 that says why `config` is not an agent the bot could run, or None if it is."""
    try:
        AgentBuilder.from_dict(config)
        return None
    except ValueError as error:
        problem = {"detail": str(error)}
        # Only the fields that apply: a problem with the agent as a whole
        # (no nodes, no start) names neither.
        for field in ("node", "edge"):
            if getattr(error, field, None) is not None:
                problem[field] = getattr(error, field)
    except (KeyError, TypeError) as error:
        # agent_builder reports problems as ValueError. This is the net under
        # it: a shape it did not foresee is still the client's 422, not a 500.
        reason = (
            f"missing field {error}" if isinstance(error, KeyError) else f"wrong type ({error})"
        )
        problem = {"detail": f"Invalid agent: {reason}."}
    return JSONResponse(status_code=422, content=problem)


def _not_found(agent_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No agent with id '{agent_id}'.")


@router.get("", response_model=list[AgentSummary])
def list_agents() -> list[dict]:
    # A summary per agent, not the full graph: the list only needs enough to
    # show a row and link to the agent.
    return [
        {
            "id": record["id"],
            "name": record["config"]["name"],
            "nodes": len(record["config"]["nodes"]),
            "updated_at": record["updated_at"],
        }
        for record in store.list_agents()
    ]


@router.get("/{agent_id}", response_model=AgentRecord, responses=_NOT_FOUND)
def get_agent(agent_id: str) -> dict:
    record = store.get_agent(agent_id)
    if record is None:
        raise _not_found(agent_id)
    return record


@router.post("", status_code=201, response_model=AgentRecord, responses=_INVALID)
def create_agent(save: AgentSave) -> Any:
    if problem := _problem(save.config):
        return problem
    return store.create_agent(save.config, save.positions())


@router.put("/{agent_id}", response_model=AgentRecord, responses=_NOT_FOUND | _INVALID)
def update_agent(agent_id: str, save: AgentSave) -> Any:
    # Replaces the whole agent: the editor always holds the full graph, and a
    # partial update could leave edges pointing at nodes that are gone.
    if problem := _problem(save.config):
        return problem
    record = store.update_agent(agent_id, save.config, save.positions())
    if record is None:
        raise _not_found(agent_id)
    return record
