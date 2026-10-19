#
# Calls — what callers got from an agent's live version, and how Prosper AI
# read each one.
#
# There is no phone line behind this builder and no real call data, so calls
# are made by simulated callers (copilot/calls.py): a batch of them, a "play",
# runs on the live version through the same text pipeline the tests use. A
# call is stored as it ends, with the version that answered it, its path and
# its transcript; Prosper AI's review of it (the outcome, the checks it applied
# and whether each passed) is added a moment later. What went wrong is a
# finding, kept with the issue it was grouped into (issues.py).
#
# A play records how many callers it has and what it spent, so the Calls page
# can say "7 of 12" while they come in, and the cost of a batch is measured
# rather than guessed. Only one play per agent runs at a time.
#

import json
import sqlite3
from typing import Optional

from .db import Conflict, NotFound, connect, now
from .versions import live_version

SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    state TEXT NOT NULL,  -- working, done, failed, stopped
    callers INTEGER NOT NULL DEFAULT 0,  -- how many calls it makes, once Prosper AI picked them
    usage TEXT NOT NULL DEFAULT '{}',  -- USD spent, by what: callers, calls, reviews
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
)""",
    """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    play INTEGER,
    version INTEGER NOT NULL,  -- the version that answered
    caller TEXT NOT NULL,  -- the caller's name
    situation TEXT NOT NULL,  -- who they are and what they want, as the simulated caller played it
    at TEXT NOT NULL,
    seconds INTEGER NOT NULL,  -- estimated from the transcript: there was no audio
    ended TEXT NOT NULL,  -- how it ended: agent_ended, caller_hung_up, turn_cap, stuck...
    path TEXT NOT NULL,
    transcript TEXT NOT NULL,
    review TEXT NOT NULL DEFAULT 'pending',  -- pending, done, failed
    outcome TEXT,  -- booked, rescheduled, cancelled, callback, answered, hung_up
    checks TEXT NOT NULL DEFAULT '[]',  -- [{ text, passed, rule }]: what Prosper AI checked
    usage TEXT NOT NULL DEFAULT '{}'  -- USD: the call itself (agent and caller), its review
)""",
)

OUTCOMES = ("booked", "rescheduled", "cancelled", "callback", "answered", "hung_up")


def _play(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return {
        "id": row["id"],
        "version": row["version"],
        "state": row["state"],
        "callers": row["callers"],
        "usage": json.loads(row["usage"]),
        "error": row["error"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _require_agent(conn: sqlite3.Connection, agent_id: str) -> None:
    if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
        raise NotFound(f"No agent with id '{agent_id}'.")


def start_play(agent_id: str) -> dict:
    """Record a new batch of calls on the live version. Returns it.

    Raises NotFound, or Conflict if the agent is not live or a batch is still going.
    """
    with connect() as conn:
        _require_agent(conn, agent_id)
        live = live_version(conn, agent_id)
        if live == 0:
            raise Conflict("The agent is not live yet: calls reach it once PR #1 is merged.")
        going = conn.execute(
            "SELECT 1 FROM plays WHERE agent_id = ? AND state = 'working'", (agent_id,)
        ).fetchone()
        if going:
            raise Conflict("Calls are still coming in.")
        (play_id,) = conn.execute(
            "INSERT INTO plays (agent_id, version, state, started_at) VALUES (?, ?, 'working', ?)"
            " RETURNING id",
            (agent_id, live, now()),
        ).fetchone()
        return _play(conn.execute("SELECT * FROM plays WHERE id = ?", (play_id,)).fetchone())


def update_play(play_id: int, **fields) -> None:
    """Set the batch's `callers`, `state` or `error`; a final state stamps when it finished."""
    if fields.get("state") in ("done", "failed", "stopped"):
        fields["finished_at"] = now()
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connect() as conn:
        conn.execute(f"UPDATE plays SET {assignments} WHERE id = ?", (*fields.values(), play_id))


def spend(play_id: int, what: str, usd: float) -> None:
    """Add `usd` to what the batch spent on `what` (callers, calls or reviews)."""
    with connect() as conn:
        row = conn.execute("SELECT usage FROM plays WHERE id = ?", (play_id,)).fetchone()
        if row is None:
            return
        usage = json.loads(row["usage"])
        usage[what] = round(usage.get(what, 0) + usd, 4)
        conn.execute("UPDATE plays SET usage = ? WHERE id = ?", (json.dumps(usage), play_id))


def latest_play(agent_id: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM plays WHERE agent_id = ? ORDER BY id DESC LIMIT 1", (agent_id,)
        ).fetchone()
        return _play(row)


def add_call(
    agent_id: str,
    play: Optional[int],
    version: int,
    caller: str,
    situation: str,
    call: dict,
    seconds: int,
    usage: dict,
) -> int:
    """Store a call that just ended, before its review. Returns its id.

    `call` is what a text call returns: its path, transcript and how it ended.
    """
    with connect() as conn:
        (call_id,) = conn.execute(
            "INSERT INTO calls (agent_id, play, version, caller, situation, at, seconds, ended,"
            " path, transcript, usage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                agent_id,
                play,
                version,
                caller,
                situation,
                now(),
                seconds,
                call["ended"],
                json.dumps(call["path"]),
                json.dumps(call["transcript"]),
                json.dumps(usage),
            ),
        ).fetchone()
        return call_id


def write_review(
    conn: sqlite3.Connection, call_id: int, outcome: str, checks: list, usd: float
) -> None:
    """Add Prosper AI's review to the call: its outcome and the checks it applied.

    Takes the caller's transaction: the review lands with the findings it
    filed (issues.file_review), or neither does.
    """
    row = conn.execute("SELECT usage FROM calls WHERE id = ?", (call_id,)).fetchone()
    if row is None:
        return
    usage = {**json.loads(row["usage"]), "review": usd}
    conn.execute(
        "UPDATE calls SET review = 'done', outcome = ?, checks = ?, usage = ? WHERE id = ?",
        (outcome, json.dumps(checks), json.dumps(usage), call_id),
    )


def review_failed(call_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE calls SET review = 'failed' WHERE id = ?", (call_id,))


def _summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "play": row["play"],
        "version": row["version"],
        "caller": row["caller"],
        "at": row["at"],
        "seconds": row["seconds"],
        "ended": row["ended"],
        "review": row["review"],
        "outcome": row["outcome"],
        # The issues its findings were grouped into, in the order they were found.
        "issues": json.loads(row["issues"]) if row["issues"] else [],
    }


_ISSUES = """
(SELECT json_group_array(issue) FROM
    (SELECT issue FROM findings WHERE findings.call_id = calls.id
     GROUP BY issue ORDER BY MIN(id))
) AS issues
"""


def list_calls(agent_id: str) -> list[dict]:
    """The agent's calls, latest first, each with the issues it is part of."""
    with connect() as conn:
        _require_agent(conn, agent_id)
        rows = conn.execute(
            f"SELECT calls.*, {_ISSUES} FROM calls WHERE agent_id = ? ORDER BY id DESC",
            (agent_id,),
        ).fetchall()
        return [_summary(row) for row in rows]


def get_call(agent_id: str, call_id: int) -> Optional[dict]:
    """The call with its transcript, path, checks and what Prosper AI found in it."""
    with connect() as conn:
        row = conn.execute(
            f"SELECT calls.*, {_ISSUES} FROM calls WHERE agent_id = ? AND id = ?",
            (agent_id, call_id),
        ).fetchone()
        if row is None:
            return None
        findings = conn.execute(
            "SELECT findings.*, issues.title, issues.state FROM findings JOIN issues"
            " ON issues.agent_id = findings.agent_id AND issues.number = findings.issue"
            " WHERE findings.call_id = ? ORDER BY findings.id",
            (call_id,),
        ).fetchall()
        return {
            **_summary(row),
            "situation": row["situation"],
            "path": json.loads(row["path"]),
            "transcript": json.loads(row["transcript"]),
            "checks": json.loads(row["checks"]),
            "usage": json.loads(row["usage"]),
            "findings": [
                {
                    "issue": f["issue"],
                    "title": f["title"],
                    "state": f["state"],
                    "check": f["check_text"],
                    "step": f["step"],
                    "turn": f["turn"],
                    "quote": f["quote"],
                    "why": f["why"],
                }
                for f in findings
            ],
        }


def stop_unfinished(conn: sqlite3.Connection) -> None:
    """Mark as stopped the batches a stopped server left going, and their unread calls failed.

    Batches run in the server's process: after a restart nothing is making
    those calls or reviewing them any more, and a batch left "working" would
    refuse every new one.
    """
    conn.execute(
        "UPDATE plays SET state = 'stopped', finished_at = ? WHERE state = 'working'", (now(),)
    )
    conn.execute("UPDATE calls SET review = 'failed' WHERE review = 'pending'")
