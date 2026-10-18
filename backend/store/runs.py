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
# A run left unfinished by a server that stopped is marked "stopped" when the
# next one starts: nothing is running it any more.
#

import json
import sqlite3
from typing import Optional

from .db import connect, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    pull INTEGER,  -- the pull request whose copy it ran on
    version INTEGER,  -- the version it ran on, or became once its pull request merged
    state TEXT NOT NULL,  -- running, done, stopped
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
            "INSERT INTO runs (agent_id, pull, version, state, repeats, tests, started_at,"
            " finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                agent_id,
                pull,
                version,
                "running" if tests else "done",
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


def finish_run(run_id: int, state: str = "done") -> Optional[dict]:
    """Mark the run done (or stopped). Returns it, or None if it was replaced meanwhile."""
    with connect() as conn:
        conn.execute(
            "UPDATE runs SET state = ?, finished_at = ? WHERE id = ? AND state = 'running'",
            (state, now(), run_id),
        )
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _to_record(row) if row else None


def stop_unfinished(conn: sqlite3.Connection) -> None:
    """Mark as stopped the runs a stopped server left running."""
    conn.execute(
        "UPDATE runs SET state = 'stopped', finished_at = ? WHERE state = 'running'", (now(),)
    )


def summary(run: Optional[dict]) -> Optional[dict]:
    """What a list shows of a run: its state and how many tests pass or fail so far.

    `state` is "running", "passed", "failed" or "stopped". A test passes when
    all of its repeats did, and fails as soon as one of them did not.
    """
    if run is None:
        return None
    passed = sum(
        1
        for test in run["tests"]
        if len(test["runs"]) == run["repeats"] and all(r["passed"] for r in test["runs"])
    )
    failing = sum(1 for test in run["tests"] if any(not r["passed"] for r in test["runs"]))
    state = run["state"]
    if state == "done":
        state = "failed" if failing else "passed"
    return {"state": state, "passed": passed, "failing": failing, "total": len(run["tests"])}


def merge_blocker(run: Optional[dict]) -> Optional[str]:
    """Why a copy with this last run cannot go live, or None if its checks pass."""
    checks = summary(run)
    if checks is None:
        return "Its checks have not run yet: run them first."
    if checks["state"] == "running":
        return "Its checks are still running."
    if checks["state"] == "stopped":
        return "Its checks did not finish: run them again."
    if checks["failing"]:
        tests = "test" if checks["failing"] == 1 else "tests"
        return f"{checks['failing']} {tests} failing."
    return None
