#
# Test calls — the voice calls a person places from Build to try the agent,
# kept apart from the calls callers make.
#
# A test call is stored as it ends, by the voice pipeline that ran it (its
# record, TestCallRecord in api/calls.py, which bot.py wires in): what it ran
# on (the live version, or a pull request's copy), who placed it, when, how
# long it really lasted, how it ended, the path the call took and what both
# sides said. Nobody reviews it on its own
# and it never opens an issue: a person trying an agent is not a caller the
# clinic missed. Prosper AI can review one when asked; what it found is kept
# on the test call, and only shown there.
#

import json
import sqlite3
from typing import Optional

from .db import NotFound, connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS test_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    pull INTEGER,  -- the pull request whose copy it called, or NULL for live
    version INTEGER,  -- the live version it called, when it called live
    by TEXT NOT NULL,  -- who placed it
    at TEXT NOT NULL,  -- when it started
    seconds INTEGER NOT NULL,  -- how long it lasted: it was audio
    ended TEXT NOT NULL,  -- agent_ended or caller_hung_up
    path TEXT NOT NULL,
    transcript TEXT NOT NULL,
    review TEXT NOT NULL DEFAULT 'none',  -- none, pending, done, failed: Prosper AI's, if asked
    outcome TEXT,
    checks TEXT NOT NULL DEFAULT '[]',  -- [{ text, passed, rule }]
    findings TEXT NOT NULL DEFAULT '[]',  -- [{ check, step, turn, quote, why, title, ... }]
    usage TEXT NOT NULL DEFAULT '{}'  -- USD: its review
)"""


def add_test_call(
    agent_id: str,
    pull: Optional[int],
    version: Optional[int],
    by: str,
    at: str,
    seconds: int,
    ended: str,
    path: list,
    transcript: list,
) -> Optional[int]:
    """Store a test call that just ended. Returns its id, or None if the agent is gone."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
            return None  # deleted while it was being called
        (call_id,) = conn.execute(
            "INSERT INTO test_calls (agent_id, pull, version, by, at, seconds, ended, path,"
            " transcript) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                agent_id,
                pull,
                version,
                by,
                at,
                seconds,
                ended,
                json.dumps(path),
                json.dumps(transcript),
            ),
        ).fetchone()
        return call_id


def _summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "pull": row["pull"],
        "version": row["version"],
        "by": row["by"],
        "at": row["at"],
        "seconds": row["seconds"],
        "ended": row["ended"],
        "review": row["review"],
        "outcome": row["outcome"],
        "flagged": len(json.loads(row["findings"])),
    }


def list_test_calls(agent_id: str) -> list[dict]:
    """The agent's test calls, latest first."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
            raise NotFound(f"No agent with id '{agent_id}'.")
        rows = conn.execute(
            "SELECT * FROM test_calls WHERE agent_id = ? ORDER BY id DESC", (agent_id,)
        ).fetchall()
        return [_summary(row) for row in rows]


def get_test_call(agent_id: str, call_id: int) -> Optional[dict]:
    """The test call with its path, transcript and, once reviewed, what Prosper AI found."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM test_calls WHERE agent_id = ? AND id = ?", (agent_id, call_id)
        ).fetchone()
        if row is None:
            return None
        return {
            **_summary(row),
            "path": json.loads(row["path"]),
            "transcript": json.loads(row["transcript"]),
            "checks": json.loads(row["checks"]),
            "findings": json.loads(row["findings"]),
            "usage": json.loads(row["usage"]),
        }


def start_review(agent_id: str, call_id: int) -> bool:
    """Mark the test call as being reviewed. False if it already is."""
    with connect() as conn:
        updated = conn.execute(
            "UPDATE test_calls SET review = 'pending' WHERE agent_id = ? AND id = ?"
            " AND review != 'pending'",
            (agent_id, call_id),
        )
        return updated.rowcount == 1


def write_review(call_id: int, outcome: str, checks: list, findings: list, usd: float) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE test_calls SET review = 'done', outcome = ?, checks = ?, findings = ?,"
            " usage = ? WHERE id = ?",
            (
                outcome,
                json.dumps(checks),
                json.dumps(findings),
                json.dumps({"review": usd}),
                call_id,
            ),
        )


def review_failed(call_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE test_calls SET review = 'failed' WHERE id = ?", (call_id,))


def stop_unfinished(conn: sqlite3.Connection) -> None:
    """Reviews run in the server's process: after a restart, nobody is doing those still pending."""
    conn.execute("UPDATE test_calls SET review = 'failed' WHERE review = 'pending'")
