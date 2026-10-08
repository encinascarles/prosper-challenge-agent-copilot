#
# Agents API — the routes the graph editor uses to list and open agents.
#
# Thin on purpose: HTTP in, store call, HTTP out. Persistence lives in `store`,
# the agent contract in `agent_builder`.
#
# Handlers are plain `def`: sqlite3 blocks, and FastAPI runs sync handlers in a
# thread pool, which keeps them off the event loop the voice pipeline runs on.
#

from fastapi import APIRouter, HTTPException

import store

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
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


@router.get("/{agent_id}")
def get_agent(agent_id: str) -> dict:
    record = store.get_agent(agent_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No agent with id '{agent_id}'.")
    return record
