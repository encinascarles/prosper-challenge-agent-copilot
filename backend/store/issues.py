#
# Issues — what went wrong in an agent's calls, grouped by problem.
#
# Prosper AI reviews every call (copilot/calls.py). Each thing that went wrong
# is a finding: the step, the turn it happened on (its index in the transcript
# and its words) and why it matters. A finding either joins an issue that is
# still being tracked, the same problem, or opens a new one; an issue keeps
# the step it was first seen in.
# So an issue is a problem with its calls, not one call: "3 calls" says how
# often callers hit it.
#
# Issues are numbered from the agent's counter, shared with pull requests:
# "Issue #3" and "PR #4" never name the same thing, and the pull request that
# fixes an issue can point at it unambiguously.
#
# An issue is open, snoozed, resolved or ignored. Snoozed comes back on its own:
# after a day, a week, or once a new version is live (a fix may have shipped).
# That is checked whenever issues are read, so nothing has to wake it up.
# Ignored is "not worth fixing": it leaves the open list but keeps collecting
# its calls, so how often it happens stays known. Resolved stops collecting:
# if the problem comes back, it is a new issue.
#
# What happened to an issue (opened from a call, seen again, snoozed,
# resolved...) is a small log kept in its row, like a pull request's.
#

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import Conflict, NotFound, connect, now
from .versions import live_version

SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS issues (
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    number INTEGER NOT NULL,  -- from the agent's counter, shared with pull requests
    title TEXT NOT NULL,
    step TEXT NOT NULL,
    severity TEXT NOT NULL,  -- safety, booking, experience
    description TEXT NOT NULL,
    state TEXT NOT NULL,  -- open, snoozed, resolved, ignored
    snooze TEXT,  -- { until: ISO time } or { version: n }: when a snoozed issue comes back
    events TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, number)
)""",
    """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    call_id INTEGER NOT NULL REFERENCES calls (id) ON DELETE CASCADE,
    issue INTEGER NOT NULL,
    check_text TEXT NOT NULL,  -- the check of the call's review it failed
    step TEXT NOT NULL,
    turn INTEGER NOT NULL,  -- index of the line in the call's transcript
    quote TEXT NOT NULL,
    why TEXT NOT NULL,
    FOREIGN KEY (agent_id, issue) REFERENCES issues (agent_id, number) ON DELETE CASCADE
)""",
)

SEVERITIES = ("safety", "booking", "experience")
# Still being tracked: a new finding with the same problem joins one of these.
TRACKED = ("open", "snoozed", "ignored")
SNOOZES = {"day": timedelta(days=1), "week": timedelta(days=7)}
PROSPER = "Prosper AI"


def label(number: int) -> str:
    return f"Issue #{number}"


def _event(kind: str, by: str, **more) -> dict:
    return {"type": kind, "by": by, "at": now(), **more}


def _wake(conn: sqlite3.Connection, agent_id: str) -> None:
    """Open again the agent's snoozed issues whose snooze is over."""
    rows = conn.execute(
        "SELECT number, snooze, events FROM issues WHERE agent_id = ? AND state = 'snoozed'",
        (agent_id,),
    ).fetchall()
    if not rows:
        return
    live = live_version(conn, agent_id)
    at = now()
    for row in rows:
        snooze = json.loads(row["snooze"] or "{}")
        over = ("until" in snooze and snooze["until"] <= at) or (
            "version" in snooze and live > snooze["version"]
        )
        if not over:
            continue
        why = f"v{live} is live" if "version" in snooze else "its snooze ended"
        events = [*json.loads(row["events"]), _event("woke", "snooze", text=why)]
        conn.execute(
            "UPDATE issues SET state = 'open', snooze = NULL, events = ?, updated_at = ?"
            " WHERE agent_id = ? AND number = ?",
            (json.dumps(events), at, agent_id, row["number"]),
        )


_COUNTS = """
SELECT issues.*,
    (SELECT COUNT(DISTINCT call_id) FROM findings
        WHERE findings.agent_id = issues.agent_id AND findings.issue = issues.number) AS calls,
    (SELECT MIN(calls.at) FROM findings JOIN calls ON calls.id = findings.call_id
        WHERE findings.agent_id = issues.agent_id AND findings.issue = issues.number) AS first_seen,
    (SELECT MAX(calls.at) FROM findings JOIN calls ON calls.id = findings.call_id
        WHERE findings.agent_id = issues.agent_id AND findings.issue = issues.number) AS last_seen
FROM issues
"""


def _to_record(row: sqlite3.Row) -> dict:
    return {
        "number": row["number"],
        "title": row["title"],
        "step": row["step"],
        "severity": row["severity"],
        "description": row["description"],
        "state": row["state"],
        "snooze": json.loads(row["snooze"]) if row["snooze"] else None,
        "calls": row["calls"],
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _require_agent(conn: sqlite3.Connection, agent_id: str) -> None:
    if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
        raise NotFound(f"No agent with id '{agent_id}'.")


def list_issues(agent_id: str) -> list[dict]:
    """The agent's issues, newest first, each with how many calls it has and when."""
    with connect() as conn:
        _require_agent(conn, agent_id)
        _wake(conn, agent_id)
        rows = conn.execute(
            f"{_COUNTS} WHERE agent_id = ? ORDER BY number DESC", (agent_id,)
        ).fetchall()
        return [_to_record(row) for row in rows]


def tracked(agent_id: str) -> list[dict]:
    """The issues a new finding may join: those still tracked (open, snoozed or ignored)."""
    return [issue for issue in list_issues(agent_id) if issue["state"] in TRACKED]


def _select(conn: sqlite3.Connection, agent_id: str, number: int) -> Optional[dict]:
    row = conn.execute(
        f"{_COUNTS} WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    if row is None:
        return None
    issue = _to_record(row)
    issue["events"] = json.loads(row["events"])
    found = conn.execute(
        "SELECT findings.*, calls.caller, calls.at, calls.seconds, calls.outcome,"
        " calls.version, calls.transcript FROM findings JOIN calls ON calls.id = findings.call_id"
        " WHERE findings.agent_id = ? AND findings.issue = ? ORDER BY calls.id DESC",
        (agent_id, number),
    ).fetchall()
    issue["findings"] = []
    for f in found:
        transcript = json.loads(f["transcript"])
        # The bad turn with the line before it: what the agent was answering.
        start = max(0, f["turn"] - 1)
        issue["findings"].append(
            {
                "call": f["call_id"],
                "caller": f["caller"],
                "at": f["at"],
                "seconds": f["seconds"],
                "outcome": f["outcome"],
                "version": f["version"],
                "check": f["check_text"],
                "turn": f["turn"],
                "quote": f["quote"],
                "why": f["why"],
                "lines": [
                    {**line, "index": start + i}
                    for i, line in enumerate(transcript[start : f["turn"] + 1])
                ],
            }
        )
    return issue


def get_issue(agent_id: str, number: int) -> Optional[dict]:
    """The issue with its calls (each with the bad turn) and its log, or None."""
    with connect() as conn:
        _wake(conn, agent_id)
        return _select(conn, agent_id, number)


def file_finding(
    agent_id: str,
    call_id: int,
    caller: str,
    finding: dict,
    issue: Optional[int] = None,
) -> int:
    """Keep a finding of the call in issue `issue`, or in a new issue. Returns its number.

    `finding` is { check, step, turn, quote, why } and, for a new issue, its
    { title, severity, description }. An issue it joins must still be tracked.
    """
    with connect() as conn:
        if issue is None:
            (issue,) = conn.execute(
                "UPDATE agents SET next_number = next_number + 1 WHERE id = ?"
                " RETURNING next_number - 1",
                (agent_id,),
            ).fetchone()
            opened = _event("opened", PROSPER, call=call_id, caller=caller)
            conn.execute(
                "INSERT INTO issues (agent_id, number, title, step, severity, description, state,"
                " snooze, events, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'open', NULL, ?, ?, ?)",
                (
                    agent_id,
                    issue,
                    finding["title"],
                    finding["step"],
                    finding["severity"],
                    finding["description"],
                    json.dumps([opened]),
                    opened["at"],
                    opened["at"],
                ),
            )
        else:
            row = conn.execute(
                "SELECT state, events FROM issues WHERE agent_id = ? AND number = ?",
                (agent_id, issue),
            ).fetchone()
            if row is None or row["state"] not in TRACKED:
                raise Conflict(f"{label(issue)} is not being tracked.")
            seen = _event("seen", PROSPER, call=call_id, caller=caller)
            conn.execute(
                "UPDATE issues SET events = ?, updated_at = ? WHERE agent_id = ? AND number = ?",
                (json.dumps([*json.loads(row["events"]), seen]), seen["at"], agent_id, issue),
            )
        conn.execute(
            "INSERT INTO findings (agent_id, call_id, issue, check_text, step, turn, quote, why)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                call_id,
                issue,
                finding["check"],
                finding["step"],
                finding["turn"],
                finding["quote"],
                finding["why"],
            ),
        )
        return issue


def _change(conn, agent_id: str, number: int, allowed: tuple, state: str, event: dict, snooze=None):
    _require_agent(conn, agent_id)
    _wake(conn, agent_id)
    row = conn.execute(
        "SELECT state, events FROM issues WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    if row is None:
        raise NotFound(f"The agent has no {label(number)}.")
    if row["state"] not in allowed:
        raise Conflict(f"{label(number)} is {row['state']}.")
    conn.execute(
        "UPDATE issues SET state = ?, snooze = ?, events = ?, updated_at = ?"
        " WHERE agent_id = ? AND number = ?",
        (
            state,
            None if snooze is None else json.dumps(snooze),
            json.dumps([*json.loads(row["events"]), event]),
            event["at"],
            agent_id,
            number,
        ),
    )
    return _select(conn, agent_id, number)


def snooze(agent_id: str, number: int, until: str, by: str) -> dict:
    """Put an open issue aside until `until`: "day", "week" or "version" (the next one)."""
    with connect() as conn:
        if until == "version":
            when = {"version": live_version(conn, agent_id)}
            text = "until the next version"
        else:
            later = datetime.now(timezone.utc) + SNOOZES[until]
            when = {"until": later.isoformat(timespec="milliseconds")}
            text = f"for a {until}"
        event = _event("snoozed", by, text=text, **when)
        return _change(conn, agent_id, number, ("open",), "snoozed", event, when)


def resolve(agent_id: str, number: int, by: str) -> dict:
    with connect() as conn:
        event = _event("resolved", by)
        return _change(conn, agent_id, number, ("open", "snoozed"), "resolved", event)


def ignore(agent_id: str, number: int, by: str) -> dict:
    with connect() as conn:
        event = _event("ignored", by)
        return _change(conn, agent_id, number, ("open", "snoozed"), "ignored", event)


def reopen(agent_id: str, number: int, by: str) -> dict:
    """Open a snoozed, resolved or ignored issue again."""
    with connect() as conn:
        event = _event("reopened", by)
        allowed = ("snoozed", "resolved", "ignored")
        return _change(conn, agent_id, number, allowed, "open", event)
