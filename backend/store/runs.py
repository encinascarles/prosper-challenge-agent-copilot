#
# Runs — the results of running a copy's tests: its checks.
#
# A run belongs to a pull request's copy (it starts on every change to it) or
# to a version (run by hand on live). When a pull request merges, its last run
# becomes its version's too: it ran on that very copy. Only the latest run of
# each is kept, because that is all anything shows: a new run replaces the one
# before, and with it whatever it had found.
#
# Each test runs several times (`repeats`), since a simulated call does not
# always go the same way. A test passes when every one of its runs did. The
# results are written as each run finishes, so a screen can show them coming
# in; they are one JSON list in the row, read and written whole.
#
# A run records the fingerprint of what it ran on (suite.py: config, rules
# and tests). That is how a merge knows the run is about the copy as it is now,
# and how a change that does not touch them (moving cards) keeps its run
# instead of paying for the same calls again.
#
# One test can also be run again on its own, into the latest run, but only
# while that run is about the copy as it is (same fingerprint): its other
# results still hold, so the run says what the whole suite does without
# paying for it again. A run whose tests did not all get their calls ends
# "stopped", whatever stopped them, so it never reads as passing.
#
# A run left unfinished by a server that stopped is marked "stopped" when the
# next one starts: nothing is running it any more.
#

import json
import sqlite3
from typing import Optional

from .db import Conflict, NotFound, connect, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    pull INTEGER,  -- the pull request whose copy it ran on
    version INTEGER,  -- the version it ran on, or became once its pull request merged
    state TEXT NOT NULL,  -- running, done, stopped
    fingerprint TEXT,  -- of the config, rules and tests it ran on
    repeats INTEGER NOT NULL,
    tests TEXT NOT NULL,  -- [{ id, name, runs: [...] }], in the order of the suite
    started_at TEXT NOT NULL,
    finished_at TEXT
)"""


def _to_record(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "pull": row["pull"],
        "version": row["version"],
        "state": row["state"],
        "fingerprint": row["fingerprint"],
        "repeats": row["repeats"],
        "tests": json.loads(row["tests"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _where(pull: Optional[int], version: Optional[int]) -> tuple[str, tuple]:
    if pull is not None:
        return "pull = ?", (pull,)
    return "version = ?", (version,)


def select_run(
    conn: sqlite3.Connection,
    agent_id: str,
    pull: Optional[int] = None,
    version: Optional[int] = None,
) -> Optional[dict]:
    where, args = _where(pull, version)
    row = conn.execute(
        f"SELECT * FROM runs WHERE agent_id = ? AND {where} ORDER BY id DESC LIMIT 1",
        (agent_id, *args),
    ).fetchone()
    return _to_record(row) if row else None


def get_run(agent_id: str, pull: Optional[int] = None, version: Optional[int] = None):
    """The latest run on the pull request's copy or on the version, or None."""
    with connect() as conn:
        return select_run(conn, agent_id, pull, version)


def start_run(
    agent_id: str,
    tests: list,
    repeats: int,
    fingerprint: str,
    pull: Optional[int] = None,
    version: Optional[int] = None,
) -> dict:
    """Record a new run of `tests` on the pull request or the version, replacing the last one.

    With no tests there is nothing to run: it is done as it starts.
    """
    at = now()
    with connect() as conn:
        if pull is not None:
            conn.execute("DELETE FROM runs WHERE agent_id = ? AND pull = ?", (agent_id, pull))
        else:
            # A version's run that came with its pull request stays that pull
            # request's; the version only stops pointing at it.
            conn.execute(
                "DELETE FROM runs WHERE agent_id = ? AND version = ? AND pull IS NULL",
                (agent_id, version),
            )
            conn.execute(
                "UPDATE runs SET version = NULL WHERE agent_id = ? AND version = ?",
                (agent_id, version),
            )
        entries = [{"id": test["id"], "name": test["name"], "runs": []} for test in tests]
        (run_id,) = conn.execute(
            "INSERT INTO runs (agent_id, pull, version, state, fingerprint, repeats, tests,"
            " started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                agent_id,
                pull,
                version,
                "running" if tests else "done",
                fingerprint,
                repeats,
                json.dumps(entries),
                at,
                None if tests else at,
            ),
        ).fetchone()
        return _to_record(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())


def add_result(run_id: int, test_id: str, result: dict) -> None:
    """Add one finished run of the test to the run's results."""
    with connect() as conn:
        row = conn.execute("SELECT tests FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return  # replaced by a newer run meanwhile
        tests = json.loads(row["tests"])
        for test in tests:
            if test["id"] == test_id:
                test["runs"].append(result)
        conn.execute("UPDATE runs SET tests = ? WHERE id = ?", (json.dumps(tests), run_id))


def rerun_test(run_id: int, test_id: str) -> dict:
    """Clear the test's results in the run and mark it running again, for that test alone.

    Raises NotFound if the run does not have the test, or Conflict if it is
    still running: two runs writing one row would mix their results.
    """
    with connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFound("That run is gone: run all the tests.")
        if row["state"] == "running":
            raise Conflict("The tests are running: wait for them to finish.")
        tests = json.loads(row["tests"])
        if not any(test["id"] == test_id for test in tests):
            raise NotFound("That run does not have this test: run all the tests.")
        for test in tests:
            if test["id"] == test_id:
                test["runs"] = []
        conn.execute(
            "UPDATE runs SET tests = ?, state = 'running', finished_at = NULL WHERE id = ?",
            (json.dumps(tests), run_id),
        )
        return _to_record(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())


def finish_run(run_id: int, state: str = "done") -> Optional[dict]:
    """Mark the run done (or stopped). Returns it, or None if it was replaced meanwhile.

    A run that is not done with every test (one test run alone) is stopped:
    "done" is what says the whole suite ran.
    """
    with connect() as conn:
        row = conn.execute("SELECT repeats, tests FROM runs WHERE id = ?", (run_id,)).fetchone()
        if state == "done" and row is not None:
            tests = json.loads(row["tests"])
            if any(len(test["runs"]) < row["repeats"] for test in tests):
                state = "stopped"
        conn.execute(
            "UPDATE runs SET state = ?, finished_at = ? WHERE id = ? AND state = 'running'",
            (state, now(), run_id),
        )
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _to_record(row) if row else None


def migrate(conn: sqlite3.Connection) -> None:
    """Give runs from before fingerprints the column. Theirs stays empty: they match no copy."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    if "fingerprint" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN fingerprint TEXT")


def stop_unfinished(conn: sqlite3.Connection) -> None:
    """Mark as stopped the runs a stopped server left running."""
    conn.execute(
        "UPDATE runs SET state = 'stopped', finished_at = ? WHERE state = 'running'", (now(),)
    )


def summary(run: Optional[dict]) -> Optional[dict]:
    """What a list shows of a run: its state and how many tests pass, are flaky or fail so far.

    `state` is "running", "passed", "failed" or "stopped". A test passes when
    every one of its repeats did; it is flaky when all but one did (2 of 3);
    it fails as soon as more than one did not, and only failing tests make
    the run fail. A voice agent on an LLM does not answer the same way every
    time: 2 of 3 shows that without letting one unlucky call block a merge.
    """
    if run is None:
        return None
    counts = {"passed": 0, "flaky": 0, "failing": 0}
    for test in run["tests"]:
        kind = verdict(test, run["repeats"])
        if kind in counts:
            counts[kind] += 1
    state = run["state"]
    if state == "done":
        state = "failed" if counts["failing"] else "passed"
    return {"state": state, **counts, "total": len(run["tests"])}


def verdict(test: dict, repeats: int) -> str:
    """A test's runs so far: "passed", "flaky" (all but one passed), "failing" or "running"."""
    failed = sum(1 for r in test["runs"] if not r["passed"])
    if failed > ALLOWED_MISSES:
        return "failing"
    if len(test["runs"]) < repeats:
        return "running"
    return "flaky" if failed else "passed"


# How many of a test's runs may fail before the test does: one, of three.
ALLOWED_MISSES = 1


def is_of(run: Optional[dict], fingerprint: str) -> bool:
    """Whether the run ran on a copy with this fingerprint."""
    return run is not None and run["fingerprint"] == fingerprint


def merge_blocker(run: Optional[dict], fingerprint: str) -> Optional[str]:
    """Why a copy with this fingerprint and this last run cannot go live, or None if it can."""
    if not is_of(run, fingerprint):
        # None, or about an older copy: a change landed after it.
        return "Checks have not run on the latest change yet."
    checks = summary(run)
    if checks["state"] == "running":
        return "Its checks are still running."
    if checks["state"] == "stopped":
        return "Its checks did not finish: run them again."
    if checks["failing"]:
        tests = "test" if checks["failing"] == 1 else "tests"
        return f"{checks['failing']} {tests} failing."
    return None
