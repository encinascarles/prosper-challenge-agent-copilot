#
# api — the HTTP API the builder UI talks to. It is mounted on the Pipecat
# runner's FastAPI app, so there is one backend and one port.
#

from fastapi import FastAPI

from .agents import router
from .calls import CallError, agent_for_call, check_start


def mount(app: FastAPI) -> None:
    """Add the builder's routes, and the check on the runner's /start, to `app`."""
    app.include_router(router)
    app.middleware("http")(check_start)


__all__ = ["CallError", "agent_for_call", "mount", "router"]
