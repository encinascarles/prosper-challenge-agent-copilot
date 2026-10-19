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
# its calls, so how often it happens stays known. Resolved by hand stops
# collecting: if the problem comes back, it is a new issue.
#
# An issue is fixed by a pull request of kind "fix" that points at it (pulls.py):
# opened, closed and reopened, each logged here too. Merging it resolves the
# issue in the version it became ("Resolved by PR #5 in v2"). Such an issue is
# still joinable: a call on that version or a later one with the same problem
# opens it again ("Came back in v2"), rather than filing the same problem
# twice; a call answered by an older version, before the fix, joins it and
# leaves it resolved.
#
# What happened to an issue (opened from a call, seen again, snoozed,
# resolved...) is a small log kept in its row, like a pull request's.
#

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from .calls import write_review
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
    fixed TEXT,  -- { pull, version }: the fix that resolved it, while it stays resolved
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
    (SELECT json_group_array(json_object('number', pulls.number, 'title', pulls.title,
            'state', pulls.state, 'merged_version', pulls.merged_version))
        FROM pulls WHERE pulls.agent_id = issues.agent_id AND pulls.fixes = issues.number) AS pulls,
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
        "fixed": json.loads(row["fixed"]) if row["fixed"] else None,
        # The pull requests that fix it, open or not, newest first.
        "pulls": sorted(json.loads(row["pulls"]), key=lambda p: -p["number"]),
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


def joinable(agent_id: str) -> list[dict]:
    """The issues a new finding may join: those still tracked, and those a fix resolved."""
    return [issue for issue in list_issues(agent_id) if _joinable(issue["state"], issue["fixed"])]


def _joinable(state: str, fixed: Optional[dict]) -> bool:
    return state in TRACKED or (state == "resolved" and fixed is not None)


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


def file_review(
    agent_id: str,
    call_id: int,
    caller: str,
    placed: list[tuple[dict, Optional[int]]],
    review: dict,
) -> list[int]:
    """File a reviewed call's findings and record its review, in one write.

    `placed` is each finding with the issue it was grouped into (None for a
    new one); `review` is { outcome, checks, usd }. Returns the issue each
    finding went to. All or nothing: a call never shows half its findings,
    or issues without the checks that found them.
    """
    with connect() as conn:
        numbers = [_file(conn, agent_id, call_id, caller, f, issue) for f, issue in placed]
        write_review(conn, call_id, review["outcome"], review["checks"], review["usd"])
        return numbers


def file_finding(
    agent_id: str,
    call_id: int,
    caller: str,
    finding: dict,
    issue: Optional[int] = None,
) -> int:
    """Keep one finding of the call in issue `issue`, or in a new issue. Returns its number."""
    with connect() as conn:
        return _file(conn, agent_id, call_id, caller, finding, issue)


def _file(
    conn: sqlite3.Connection,
    agent_id: str,
    call_id: int,
    caller: str,
    finding: dict,
    issue: Optional[int],
) -> int:
    """`finding` is { check, step, turn, quote, why } and, for a new issue, its
    { title, severity, description }.

    An issue that stopped being tracked since the finding was grouped into it
    (resolved while the batch ran, say) takes no more calls: the finding opens
    a new issue, as a problem that comes back after it was resolved by hand
    does. One a fix resolved takes it: a call on the fixed version opens it
    again, one on an older version leaves it resolved.
    """
    row = None
    if issue is not None:
        row = conn.execute(
            "SELECT state, fixed, events FROM issues WHERE agent_id = ? AND number = ?",
            (agent_id, issue),
        ).fetchone()
    fixed = json.loads(row["fixed"]) if row is not None and row["fixed"] else None
    if row is None or not _joinable(row["state"], fixed):
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
        (version,) = conn.execute("SELECT version FROM calls WHERE id = ?", (call_id,)).fetchone()
        state = row["state"]
        if fixed is not None and version >= fixed["version"]:
            # The fix is in the version that answered, and the problem is still there.
            seen = _event("came_back", PROSPER, call=call_id, caller=caller, text=f"v{version}")
            state, fixed = "open", None
        else:
            seen = _event("seen", PROSPER, call=call_id, caller=caller)
        conn.execute(
            "UPDATE issues SET state = ?, fixed = ?, events = ?, updated_at = ?"
            " WHERE agent_id = ? AND number = ?",
            (
                state,
                None if fixed is None else json.dumps(fixed),
                json.dumps([*json.loads(row["events"]), seen]),
                seen["at"],
                agent_id,
                issue,
            ),
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
    # Resolved by hand or opened again, it is no longer what a fix resolved.
    conn.execute(
        "UPDATE issues SET state = ?, snooze = ?, fixed = NULL, events = ?, updated_at = ?"
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


def check_fixable(conn: sqlite3.Connection, agent_id: str, number: int) -> dict:
    """The issue, which a new pull request may fix. Raises NotFound or Conflict.

    Not one already resolved or ignored, nor one a pull request is fixing.
    """
    _require_agent(conn, agent_id)
    _wake(conn, agent_id)
    issue = _select(conn, agent_id, number)
    if issue is None:
        raise NotFound(f"The agent has no {label(number)}.")
    if issue["state"] not in ("open", "snoozed"):
        raise Conflict(f"{label(number)} is {issue['state']}.")
    if fixing := [p for p in issue["pulls"] if p["state"] == "open"]:
        raise Conflict(f"PR #{fixing[0]['number']} is fixing {label(number)} already.")
    return issue


def log_fix(conn: sqlite3.Connection, agent_id: str, number: int, kind: str, pull: int, by: str):
    """Log in the issue what happened to a pull request fixing it.

    `kind` is "fixing" (opened to fix it), "unlinked" (closed without merging)
    or "relinked" (reopened). Merging is `resolve_by_fix`.
    """
    row = conn.execute(
        "SELECT events FROM issues WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    if row is None:
        return  # deleted with nothing else: the pull request still stands on its own
    event = _event(kind, by, pull=pull)
    conn.execute(
        "UPDATE issues SET events = ?, updated_at = ? WHERE agent_id = ? AND number = ?",
        (json.dumps([*json.loads(row["events"]), event]), event["at"], agent_id, number),
    )


def resolve_by_fix(
    conn: sqlite3.Connection, agent_id: str, number: int, pull: int, version: int, by: str
):
    """The pull request fixing the issue merged as `version`, by `by`: it is resolved there.

    Unless the person already decided what the issue is: one they ignored
    stays ignored, and one already resolved keeps its first resolution. The
    merge is logged on it either way.
    """
    row = conn.execute(
        "SELECT state, events FROM issues WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    if row is None:
        return
    events = json.loads(row["events"])
    if row["state"] in ("ignored", "resolved"):
        event = _event("fix_merged", by, pull=pull, version=version, text=row["state"])
        conn.execute(
            "UPDATE issues SET events = ?, updated_at = ? WHERE agent_id = ? AND number = ?",
            (json.dumps([*events, event]), event["at"], agent_id, number),
        )
        return
    event = _event("fixed", by, pull=pull, version=version)
    conn.execute(
        "UPDATE issues SET state = 'resolved', snooze = NULL, fixed = ?, events = ?, updated_at = ?"
        " WHERE agent_id = ? AND number = ?",
        (
            json.dumps({"pull": pull, "version": version}),
            json.dumps([*events, event]),
            event["at"],
            agent_id,
            number,
        ),
    )


def migrate(conn: sqlite3.Connection) -> None:
    """Give issues from before fixes the column: none of them was resolved by one."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(issues)")}
    if columns and "fixed" not in columns:
        conn.execute("ALTER TABLE issues ADD COLUMN fixed TEXT")
