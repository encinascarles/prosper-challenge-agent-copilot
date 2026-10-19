#
# api — the HTTP API the builder UI talks to. It is mounted on the Pipecat
# runner's FastAPI app, so there is one backend and one port.
#

from fastapi import FastAPI

from . import agents, copilot, live, pulls, suite
from .calls import CallError, agent_for_call, check_start, describe


def mount(app: FastAPI) -> None:
    """Add the builder's routes, and the check on the runner's /start, to `app`."""
    # Before the agents' routes: /api/agents/from-guidelines is not an agent's id.
    app.include_router(copilot.router)
    app.include_router(agents.router)
    app.include_router(pulls.router)
    app.include_router(suite.router)
    app.include_router(live.router)
    app.middleware("http")(check_start)


__all__ = ["CallError", "agent_for_call", "describe", "mount"]
