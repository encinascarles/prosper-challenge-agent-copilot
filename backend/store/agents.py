#
# Agent store — persists agents in SQLite so the builder UI (and later the
# Copilot) can list, read, create and update them.
#
# An agent is data: the row holds the agent JSON exactly as `AgentConfig` reads
# it, in one TEXT column. Nothing queries inside the graph, so splitting nodes
# and edges into tables would only add a mapping layer to keep in sync with
# the schema.
#
# Where the editor drew each node is kept apart, in a `layout` column: the agent
# JSON is what Pipecat runs, and a position on a canvas is not part of an agent.
# The layout is keyed by node name and never names a node the agent lacks.
#
# SQLite through the stdlib `sqlite3` module: a single-process app with a
# handful of agents needs no server and no ORM, and the file survives restarts.
#
# This module only stores. Checking that a config is a valid agent is the
# caller's job (AgentBuilder), so there is one place that defines "valid". The
# one agent the store writes on its own, the seed, goes through that same check.
#

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from agent_builder import AgentBuilder

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "agents.db"
DB_PATH_ENV = "AGENTS_DB_PATH"
SEED_FLOW = BACKEND_DIR / "example_flow.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    layout TEXT NOT NULL DEFAULT '{}',
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
    """Create the schema, and seed the database if this creates it. Call when the server starts."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        # A fresh checkout should open on a working agent rather than an empty
        # list. Only a database that is being created is seeded: one whose
        # agents were all deleted stays empty, or the example would come back
        # on its own at the next start.
        new = not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agents'"
        ).fetchone()
        seed = None
        if new:
            seed = json.loads(SEED_FLOW.read_text())
            # Same check as an agent saved through the API, so every stored
            # agent has passed it. A broken sample stops the server at startup
            # with the reason, before anything is created, so the next start
            # with a fixed sample still seeds.
            AgentBuilder.from_dict(seed)
        conn.execute(_SCHEMA)
        # A database created before `layout` existed keeps its agents: the
        # column is added in place, and their nodes get placed by the editor.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(agents)")}
        if "layout" not in columns:
            conn.execute("ALTER TABLE agents ADD COLUMN layout TEXT NOT NULL DEFAULT '{}'")
        if seed is not None:
            _insert(conn, seed)


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


def _prune(layout: dict, config: dict) -> dict:
    # Done here rather than by the caller so the two columns cannot disagree,
    # whoever writes: a save that removes a node also removes its position,
    # in the same write.
    names = {node["name"] for node in config["nodes"]}
    return {name: position for name, position in layout.items() if name in names}


def _insert(conn: sqlite3.Connection, config: dict, layout: Optional[dict] = None) -> str:
    # Random id rather than one derived from the name: the name is editable and
    # the id ends up in URLs, so it must not change or collide.
    agent_id = uuid.uuid4().hex
    now = _now()
    conn.execute(
        "INSERT INTO agents (id, config, layout, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (agent_id, json.dumps(config), json.dumps(_prune(layout or {}, config)), now, now),
    )
    return agent_id


def _to_record(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "config": json.loads(row["config"]),
        "layout": json.loads(row["layout"]),
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


def create_agent(config: dict, layout: Optional[dict] = None) -> dict:
    """Store a new agent, with its layout if given, and return its record, id included."""
    with _connect() as conn:
        return _select(conn, _insert(conn, config, layout))


def update_agent(agent_id: str, config: dict, layout: Optional[dict] = None) -> Optional[dict]:
    """Replace an agent's config and, if given, its layout.

    Without a `layout` the stored one is kept. Either way, positions of nodes
    the new config does not have are dropped. Returns the new record, or None
    if the id is unknown.
    """
    with _connect() as conn:
        current = _select(conn, agent_id)
        if current is None:
            return None
        if layout is None:
            layout = current["layout"]
        conn.execute(
            "UPDATE agents SET config = ?, layout = ?, updated_at = ? WHERE id = ?",
            (json.dumps(config), json.dumps(_prune(layout, config)), _now(), agent_id),
        )
        return _select(conn, agent_id)


def delete_agent(agent_id: str) -> bool:
    """Remove an agent and its layout. Returns whether there was one with this id."""
    with _connect() as conn:
        return conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,)).rowcount > 0
