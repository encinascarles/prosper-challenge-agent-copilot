#
# Checks — running a copy's tests in the background, and keeping the results.
#
# Every change to a pull request's copy (a save, an update, a rule or a test
# added or taken out) starts its whole suite again, replacing the run in
# progress: only the run on the copy as it is now can say whether it may
# merge. A change that leaves the config, rules and tests as they were (moving
# cards) keeps the run it has: same fingerprint, same calls, nothing to pay
# for twice. A version's suite runs when someone asks, and asking always runs.
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
from copilot import setup
from store.suite import fingerprint

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


def start(
    agent_id: str, pull: Optional[int] = None, version: Optional[int] = None, again: bool = False
) -> dict:
    """Run the suite of the pull request's copy, or of the version, replacing any run on it.

    Returns the new run, as it starts. Unless `again`, a run on the same
    config, rules and tests that finished or is still going is kept and
    returned instead: running it twice would only spend more.
    """
    copy = _copy(agent_id, pull, version)
    ran_on = fingerprint(copy)
    last = store.get_run(agent_id, pull=pull, version=version)
    if not again and last is not None and last["fingerprint"] == ran_on:
        if last["state"] in ("running", "done"):
            return last
    run = store.start_run(
        agent_id, copy["tests"], simulate.REPEATS, ran_on, pull=pull, version=version
    )
    _launch(agent_id, run, copy, copy["tests"], pull, version)
    return run


def start_test(
    agent_id: str, test_id: str, pull: Optional[int] = None, version: Optional[int] = None
) -> tuple[dict, Optional[str]]:
    """Run one test of the copy again, on its own. Returns the run and, if it ran alone, why.

    Raises NotFound for a test the copy does not have, or Conflict while
    the copy's tests are running.
    """
    copy = _copy(agent_id, pull, version)
    test = next((test for test in copy["tests"] if test["id"] == test_id), None)
    if test is None:
        raise store.NotFound("There is no such test here.")
    ran_on = fingerprint(copy)
    last = store.get_run(agent_id, pull=pull, version=version)
    if store.runs.is_of(last, ran_on):
        run, alone = store.runs.rerun_test(last["id"], test_id), None
    else:
        # Nothing to merge into: the other results, if any, are about another copy.
        alone = (
            "The change moved on since the last run, so this test ran alone: run all for the rest."
            if last is not None
            else "This test ran alone: run all for the rest."
        )
        run = store.start_run(
            agent_id, copy["tests"], simulate.REPEATS, ran_on, pull, version, only=test_id
        )
    _launch(agent_id, run, copy, [test], pull, version, whole=False)
    return run, alone


def run_again(agent_id: str, pull: int, test_ids: list[str]) -> dict:
    """Run some tests of the pull request's latest run again, into it, as its suite.

    For Prosper AI: a test that was already flaky before its change gets one
    more go before it counts against the change. When they are done, Prosper
    AI looks at the checks again, as after a whole suite.
    """
    copy = _copy(agent_id, pull, None)
    last = store.get_run(agent_id, pull=pull)
    run = store.runs.rerun_tests(last["id"], test_ids)
    tests = [test for test in copy["tests"] if test["id"] in test_ids]
    _launch(agent_id, run, copy, tests, pull, None)
    return run


def _copy(agent_id: str, pull: Optional[int], version: Optional[int]) -> dict:
    if pull is not None:
        return store.get_pull(agent_id, pull)
    return store.get_version(agent_id, version)


def _launch(
    agent_id: str,
    run: dict,
    copy: dict,
    tests: list,
    pull: Optional[int],
    version: Optional[int],
    whole: bool = True,
) -> None:
    """Run `tests` into `run` on the checks' loop, replacing whatever ran on the copy.

    `whole`: they are the copy's suite, not one test looked at again.
    """
    key = (agent_id, pull, version)
    with _lock:
        before = _running.pop(key, None)
    if before is not None:
        before.cancel()
    if run["state"] == "running":
        future = asyncio.run_coroutine_threadsafe(
            _run(agent_id, run, copy, tests, pull, whole), _the_loop()
        )
        with _lock:
            _running[key] = future
        future.add_done_callback(lambda done: _forget(key, done))


def _forget(key: tuple, future: Future) -> None:
    with _lock:
        if _running.get(key) is future:
            del _running[key]


async def _run(
    agent_id: str, run: dict, copy: dict, tests: list, pull: Optional[int], whole: bool
) -> None:
    """Run `tests` of the copy into `run`; `pull`: the open pull request it is the copy of."""

    def keep(test: dict, result: dict) -> None:
        store.add_result(run["id"], test["id"], result)

    try:
        await simulate.run_suite(copy["config"], copy["rules"], tests, keep, services=services)
    except asyncio.CancelledError:
        store.finish_run(run["id"], "stopped")
        raise
    except Exception:
        logger.exception(f"Checks of agent {agent_id} did not finish")
        store.finish_run(run["id"], "stopped")
        return
    # Logged before the run is marked done, so whoever reads the pull request
    # as soon as its checks are done finds how they went in its log too. The
    # run is marked done whatever happens to the log: left "running", it would
    # keep the merge waiting until the next restart.
    try:
        if pull is not None:
            latest = store.get_run(agent_id, pull=pull)
            if latest is not None and latest["id"] == run["id"]:
                store.record_checks(agent_id, pull, latest)
    finally:
        store.finish_run(run["id"])
    # Prosper AI checks its own work after the suite its change started, not
    # after a person looked at one test again.
    if pull is not None and whole:
        try:
            setup.after_checks(agent_id, pull)
        except Exception:  # noqa: BLE001 - the run is over either way
            logger.exception(f"Prosper AI could not look at the checks of agent {agent_id}")


def wait(timeout: float = 30) -> None:
    """Wait for the runs in progress to finish. For tests, and a server shutting down."""
    with _lock:
        futures = list(_running.values())
    for future in futures:
        try:
            future.result(timeout)
        except Exception:  # noqa: BLE001 - cancelled or failed: either way, it is over
            pass
