#
# Versions — what an agent's callers get.
#
# A version is an immutable snapshot of an agent (config and layout), numbered
# v1, v2… per agent. The latest one is live: calls run on it. A version is only
# ever added, by merging a pull request (pulls.py), so each one says which pull
# request it came from, and an older one can always be read back.
#

import json
import sqlite3
from typing import Optional

from .db import connect, now, prune


def live_version(conn: sqlite3.Connection, agent_id: str) -> int:
    """The number of the agent's live version, or 0 if it has none yet."""
    (live,) = conn.execute(
        "SELECT COALESCE(MAX(number), 0) FROM versions WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    return live


def insert_version(
    conn: sqlite3.Connection,
    agent_id: str,
    config: dict,
    layout: dict,
    pull: Optional[int],
    at: Optional[str] = None,
) -> int:
    """Add the agent's next version, which makes it live. Returns its number."""
    number = live_version(conn, agent_id) + 1
    conn.execute(
        "INSERT INTO versions (agent_id, number, config, layout, pull, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            agent_id,
            number,
            json.dumps(config),
            json.dumps(prune(layout, config)),
            pull,
            at or now(),
        ),
    )
    return number


def select_version(conn: sqlite3.Connection, agent_id: str, number: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM versions WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    if row is None:
        return None
    return {
        "number": row["number"],
        "pull": row["pull"],
        "config": json.loads(row["config"]),
        "layout": json.loads(row["layout"]),
        "created_at": row["created_at"],
    }


def list_versions(agent_id: str) -> list[dict]:
    """The agent's versions, live first, each with the title of the pull request it came from."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT versions.number, versions.pull, versions.created_at, pulls.title"
            " FROM versions LEFT JOIN pulls"
            " ON pulls.agent_id = versions.agent_id AND pulls.number = versions.pull"
            " WHERE versions.agent_id = ? ORDER BY versions.number DESC",
            (agent_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_version(agent_id: str, number: int) -> Optional[dict]:
    """Version `number` of the agent, config and layout included, or None."""
    with connect() as conn:
        return select_version(conn, agent_id, number)
