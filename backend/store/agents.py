#
# Agent store — persists agents in SQLite so the builder UI (and later the
# Copilot) can list, read, create and update them.
#
# An agent is data: the row holds the agent JSON exactly as `AgentConfig` reads
# it, in one TEXT column. Nothing queries inside the graph, so splitting nodes
# and edges into tables would only add a mapping layer to keep in sync with
# the schema.
#
# SQLite through the stdlib `sqlite3` module: a single-process app with a
# handful of agents needs no server and no ORM, and the file survives restarts.
#
# This module only stores. Checking that a config is a valid agent is the
# caller's job (AgentBuilder), so there is one place that defines "valid".
#

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "agents.db"
DB_PATH_ENV = "AGENTS_DB_PATH"
SEED_FLOW = BACKEND_DIR / "example_flow.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def db_path() -> Path:
    # Read on every call, not at import, so a test can point the store at a
    # temp file after this module is already loaded.
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


def _now() -> str:
    # ISO 8601 in UTC: sorts as text and is what the browser's Date parses.
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def init_db() -> None:
    """Create the schema and seed an empty table. Call once when the server starts."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(_SCHEMA)
        # A fresh checkout should open on a working agent rather than an empty list.
        if not conn.execute("SELECT 1 FROM agents LIMIT 1").fetchone():
            _insert(conn, json.loads(SEED_FLOW.read_text()))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open the database for one operation, committing on success.

    One short-lived connection per operation: FastAPI runs sync handlers in a
    thread pool and a sqlite3 connection must stay on the thread that opened it.
    """
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _insert(conn: sqlite3.Connection, config: dict) -> str:
    # Random id rather than one derived from the name: the name is editable and
    # the id ends up in URLs, so it must not change or collide.
    agent_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        "INSERT INTO agents (id, config, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (agent_id, json.dumps(config), now, now),
    )
    return agent_id


def _to_record(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "config": json.loads(row["config"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _select(conn: sqlite3.Connection, agent_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    return _to_record(row) if row else None


def list_agents() -> list[dict]:
    """All agents, oldest first."""
    with _connect() as conn:
        # rowid breaks ties between agents created in the same millisecond.
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at, rowid").fetchall()
    return [_to_record(row) for row in rows]


def get_agent(agent_id: str) -> Optional[dict]:
    """The agent with this id, or None."""
    with _connect() as conn:
        return _select(conn, agent_id)


def create_agent(config: dict) -> dict:
    """Store a new agent and return its record, id included."""
    with _connect() as conn:
        return _select(conn, _insert(conn, config))


def update_agent(agent_id: str, config: dict) -> Optional[dict]:
    """Replace an agent's config. Returns the new record, or None if the id is unknown."""
    with _connect() as conn:
        conn.execute(
            "UPDATE agents SET config = ?, updated_at = ? WHERE id = ?",
            (json.dumps(config), _now(), agent_id),
        )
        return _select(conn, agent_id)
