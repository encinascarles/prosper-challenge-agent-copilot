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
# Handlers are plain `def`: sqlite3 blocks, and FastAPI runs sync handlers in a
# thread pool, which keeps them off the event loop the voice pipeline runs on.
#

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

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


class AgentRecord(BaseModel):
    id: str
    config: dict[str, Any]  # the agent JSON, as agent_builder/schema.py defines it
    created_at: str
    updated_at: str


class Problem(BaseModel):
    detail: str  # one sentence naming what is wrong


AgentBody = Annotated[
    dict[str, Any],
    Body(
        description="The agent JSON: name, initial_node and nodes, each node with its edges.",
        examples=[_EXAMPLE_AGENT],
    ),
]

_NOT_FOUND = {404: {"model": Problem, "description": "No agent has this id."}}
_INVALID = {422: {"model": Problem, "description": "The agent is not valid; says why."}}


def _validate(config: dict) -> None:
    """Raise a 422 with the reason unless `config` is an agent the bot could run."""
    try:
        AgentBuilder.from_dict(config)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (KeyError, TypeError) as error:
        # agent_builder reports problems as ValueError. This is the net under
        # it: a shape it did not foresee is still the client's 422, not a 500.
        reason = (
            f"missing field {error}" if isinstance(error, KeyError) else f"wrong type ({error})"
        )
        raise HTTPException(status_code=422, detail=f"Invalid agent: {reason}.") from error


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
def create_agent(config: AgentBody) -> dict:
    _validate(config)
    return store.create_agent(config)


@router.put("/{agent_id}", response_model=AgentRecord, responses=_NOT_FOUND | _INVALID)
def update_agent(agent_id: str, config: AgentBody) -> dict:
    # Replaces the whole agent: the editor always holds the full graph, and a
    # partial update could leave edges pointing at nodes that are gone.
    _validate(config)
    record = store.update_agent(agent_id, config)
    if record is None:
        raise _not_found(agent_id)
    return record
