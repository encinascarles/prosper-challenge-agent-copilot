#
# Checks — running a copy's tests in the background, and keeping the results.
#
# Every change to a pull request's copy (a save, an update, a rule or a test
# added or taken out) starts its whole suite again, replacing the run in
# progress: only the run on the copy as it is now can say whether it may
# merge. A version's suite runs when someone asks.
#
# Runs happen on one event loop in a thread of its own, not on the server's:
# a suite is a few dozen calls to the LLM at once, and the voice calls on the
# server's loop should not wait behind them. The routes that start a run return
# at once; the run writes each result to the store as it comes, and the editor
# reads them from there.
#
# `services` is who the simulated calls talk to. The tests swap it for fakes.
#

import asyncio
import threading
from concurrent.futures import Future
from typing import Optional

from loguru import logger

import simulate
import store

services: Optional[simulate.Services] = None

_loop: Optional[asyncio.AbstractEventLoop] = None
_running: dict[tuple, Future] = {}
_lock = threading.Lock()


def _the_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="checks", daemon=True).start()
        return _loop


def start(agent_id: str, pull: Optional[int] = None, version: Optional[int] = None) -> dict:
    """Run the suite of the pull request's copy, or of the version, replacing any run on it.

    Returns the new run, as it starts.
    """
    copy = store.get_pull(agent_id, pull) if pull is not None else None
    if pull is None:
        copy = store.get_version(agent_id, version)
    run = store.start_run(agent_id, copy["tests"], simulate.REPEATS, pull=pull, version=version)
    key = (agent_id, pull, version)
    with _lock:
        before = _running.pop(key, None)
    if before is not None:
        before.cancel()
    if run["state"] == "running":
        future = asyncio.run_coroutine_threadsafe(_run(agent_id, run, copy), _the_loop())
        with _lock:
            _running[key] = future
        future.add_done_callback(lambda done: _forget(key, done))
    return run


def _forget(key: tuple, future: Future) -> None:
    with _lock:
        if _running.get(key) is future:
            del _running[key]


async def _run(agent_id: str, run: dict, copy: dict) -> None:
    def keep(test: dict, result: dict) -> None:
        store.add_result(run["id"], test["id"], result)

    try:
        await simulate.run_suite(
            copy["config"], copy["rules"], copy["tests"], keep, services=services
        )
    except asyncio.CancelledError:
        store.finish_run(run["id"], "stopped")
        raise
    except Exception:
        logger.exception(f"Checks of agent {agent_id} did not finish")
        store.finish_run(run["id"], "stopped")
        return
    finished = store.finish_run(run["id"])
    if run["pull"] is not None and finished is not None:
        store.record_checks(agent_id, run["pull"], finished)


def wait(timeout: float = 30) -> None:
    """Wait for the runs in progress to finish. For tests, and a server shutting down."""
    with _lock:
        futures = list(_running.values())
    for future in futures:
        try:
            future.result(timeout)
        except Exception:  # noqa: BLE001 - cancelled or failed: either way, it is over
            pass
