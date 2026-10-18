#
# Agents API — the routes the editor uses to list, open, create and delete
# agents. What an agent is made of is in its versions and pull requests
# (versions.py, pulls.py): this is the agent as a whole.
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
# There is no route that overwrites an agent. A change is saved on a pull
# request's copy and reaches callers only when it is merged, the agent's name
# included: it is part of the agent JSON.
#
# Handlers are plain `def`: sqlite3 blocks, and FastAPI runs sync handlers in a
# thread pool, which keeps them off the event loop the voice pipeline runs on.
#

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

import store

from .models import INVALID, NOT_FOUND, YOU, AgentSave, not_found, problem
from .pulls import Pull

router = APIRouter(prefix="/api/agents", tags=["agents"])


class Agent(BaseModel):
    id: str
    name: str  # the live version's, or pull request #1's before the agent is live
    live_version: int  # the version calls run on; 0 until pull request #1 is merged
    open_pulls: int  # how many pull requests are open
    created_at: str
    updated_at: str


class NewAgent(BaseModel):
    agent: Agent
    pull: Pull  # pull request #1, holding the agent as it was sent


@router.get("", response_model=list[Agent])
def list_agents() -> list[dict]:
    return store.list_agents()


@router.get("/{agent_id}", response_model=Agent, responses=NOT_FOUND)
def get_agent(agent_id: str) -> dict:
    record = store.get_agent(agent_id)
    if record is None:
        raise not_found(agent_id)
    return record


@router.post("", status_code=201, response_model=NewAgent, responses=INVALID)
def create_agent(save: AgentSave) -> Any:
    # The agent is created with pull request #1 holding it, and is not live:
    # merging that pull request is what puts it in front of callers.
    if found := problem(save.config):
        return found
    agent, pull = store.create_agent(save.config, save.positions(), by=YOU)
    return {"agent": agent, "pull": pull}


@router.delete("/{agent_id}", status_code=204, responses=NOT_FOUND)
def delete_agent(agent_id: str) -> None:
    # For good, versions and pull requests included. The client asks before it
    # calls this.
    if not store.delete_agent(agent_id):
        raise not_found(agent_id)
