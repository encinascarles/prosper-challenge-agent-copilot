#
# Agent store — the agents themselves, and the schema of the whole store.
#
# An agent's graph is not in its row. What callers get is its latest live
# version (versions.py); a change is made on a pull request's own copy
# (pulls.py) and becomes the next version when it is merged. The row holds
# what is not versioned: the id, the name lists show, and the counter that
# numbers its pull requests.
#
# A config is stored exactly as `AgentConfig` reads it, in one TEXT column.
# Nothing queries inside the graph, so splitting nodes and edges into tables
# would only add a mapping layer to keep in sync with the schema. Where the
# editor drew each node is kept apart, in a `layout` column next to each
# config: the agent JSON is what Pipecat runs, and a position on a canvas is not
# part of an agent. A layout is keyed by node name and never names a node its
# config lacks.
#
# The sample agent is seeded with a few tests (example_tests.json), so a fresh
# checkout has a suite to run and the checks have something to say.
#
# This module only stores. Checking that a config is a valid agent is the
# caller's job (AgentBuilder), so there is one place that defines "valid". The
# one agent the store writes on its own, the seed, goes through that same check.
#

import json
import sqlite3
import uuid
from typing import Optional

from agent_builder import AgentBuilder

from . import runs
from .db import BACKEND_DIR, connect, db_path, now
from .pulls import insert_pull
from .suite import manual, new_id
from .versions import insert_version

SEED_FLOW = BACKEND_DIR / "example_flow.json"
SEED_TESTS = BACKEND_DIR / "example_tests.json"

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    -- Pull requests are numbered per agent; issues will take numbers from the
    -- same counter, so "#3" names one thing in an agent.
    next_number INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """
CREATE TABLE IF NOT EXISTS versions (
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    config TEXT NOT NULL,
    layout TEXT NOT NULL,
    rules TEXT NOT NULL DEFAULT '[]',
    tests TEXT NOT NULL DEFAULT '[]',
    pull INTEGER,  -- the pull request it was merged from; NULL if it predates them
    created_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, number)
)""",
    """
CREATE TABLE IF NOT EXISTS pulls (
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    base_version INTEGER NOT NULL,  -- 0: based on nothing, the agent was not live
    merged_version INTEGER,
    config TEXT NOT NULL,
    layout TEXT NOT NULL,
    rules TEXT NOT NULL DEFAULT '[]',
    tests TEXT NOT NULL DEFAULT '[]',
    events TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, number)
)""",
    runs.SCHEMA,
)

# What the lists and the agent's page read: the row, plus the two facts every
# screen shows about an agent. The live version is the latest one.
_SELECT = """
SELECT agents.*,
    COALESCE((SELECT MAX(number) FROM versions WHERE agent_id = agents.id), 0) AS live_version,
    (SELECT COUNT(*) FROM pulls WHERE agent_id = agents.id AND state = 'open') AS open_pulls
FROM agents
"""


def init_db() -> None:
    """Create the schema, and seed the database if this creates it. Call when the server starts."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
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
        _migrate_unversioned(conn)
        _create(conn)
        _migrate_untested(conn)
        runs.stop_unfinished(conn)
        if seed is not None:
            # The example is live from the start, as v1: it is there to be called.
            agent_id = _insert_agent(conn, seed["name"])
            tests = [
                {"id": new_id(), **test, "source": manual(None)}
                for test in json.loads(SEED_TESTS.read_text())
            ]
            insert_version(conn, agent_id, seed, {}, pull=None, tests=tests)


def _create(conn: sqlite3.Connection) -> None:
    # `executescript` would commit the transaction `connect` opened; one
    # statement at a time keeps the schema change inside it.
    for statement in _SCHEMA:
        conn.execute(statement)


def _migrate_unversioned(conn: sqlite3.Connection) -> None:
    """Turn a database from before versions into one with them, keeping every agent.

    Its agents held their graph in the row. Each one becomes live as v1, made
    from that graph and recorded as coming from no pull request, and the row
    keeps only what is not versioned. A database from before layouts had no
    `layout` column: its nodes start unplaced, and the editor lays them out.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(agents)")}
    if "config" not in columns:
        return
    rows = conn.execute("SELECT * FROM agents").fetchall()
    _create(conn)
    conn.execute("ALTER TABLE agents ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE agents ADD COLUMN next_number INTEGER NOT NULL DEFAULT 1")
    for row in rows:
        config = json.loads(row["config"])
        layout = json.loads(row["layout"]) if "layout" in columns else {}
        conn.execute("UPDATE agents SET name = ? WHERE id = ?", (config["name"], row["id"]))
        insert_version(conn, row["id"], config, layout, pull=None, at=row["updated_at"])
    conn.execute("ALTER TABLE agents DROP COLUMN config")
    if "layout" in columns:
        conn.execute("ALTER TABLE agents DROP COLUMN layout")


def _migrate_untested(conn: sqlite3.Connection) -> None:
    """Give copies from before rules and tests none of either."""
    for table in ("versions", "pulls"):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column in ("rules", "tests"):
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT '[]'")


def _insert_agent(conn: sqlite3.Connection, name: str) -> str:
    # Random id rather than one derived from the name: the name is editable and
    # the id ends up in URLs, so it must not change or collide.
    agent_id = uuid.uuid4().hex
    at = now()
    conn.execute(
        "INSERT INTO agents (id, name, next_number, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
        (agent_id, name, at, at),
    )
    return agent_id


def _to_record(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "live_version": row["live_version"],
        "open_pulls": row["open_pulls"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def select_agent(conn: sqlite3.Connection, agent_id: str) -> Optional[dict]:
    row = conn.execute(f"{_SELECT} WHERE agents.id = ?", (agent_id,)).fetchone()
    return _to_record(row) if row else None


def list_agents() -> list[dict]:
    """All agents, oldest first."""
    with connect() as conn:
        # rowid breaks ties between agents created in the same millisecond.
        rows = conn.execute(f"{_SELECT} ORDER BY agents.created_at, agents.rowid").fetchall()
    return [_to_record(row) for row in rows]


def get_agent(agent_id: str) -> Optional[dict]:
    """The agent with this id, or None."""
    with connect() as conn:
        return select_agent(conn, agent_id)


def create_agent(config: dict, layout: Optional[dict] = None, by: str = "you") -> tuple[dict, dict]:
    """Store a new agent with its first pull request, holding `config`. Returns both.

    The agent is not live: nothing reaches callers except by merging a pull
    request, the first one included.
    """
    with connect() as conn:
        agent_id = _insert_agent(conn, config["name"])
        pull = insert_pull(
            conn, agent_id, f"Set up {config['name']}", "setup", 0, config, layout or {}, by
        )
        return select_agent(conn, agent_id), pull


def delete_agent(agent_id: str) -> bool:
    """Remove an agent with its versions and pull requests. Returns whether there was one."""
    with connect() as conn:
        return conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,)).rowcount > 0
