#
# Pull requests — proposed changes to an agent, each on its own copy of it.
#
# Nothing reaches callers except by merging one. A pull request is based on the
# version that was live when it was opened and holds its own copy of the agent
# (config and layout), which is what the editor saves to. Merging turns that
# copy into the next version. A new agent starts with pull request #1, "Set up
# <name>", based on nothing: the agent goes live when it is merged.
#
# A pull request is open, merged or closed. Its small event log (opened, saved,
# merged, closed: by whom and when) is kept in the row as JSON: it is only ever
# read with the pull request it belongs to.
#
# Merging is refused once live has moved past the version the pull request was
# based on: its copy was made from an older agent, and merging it would quietly
# undo whatever was merged in between.
#

import json
import sqlite3
from typing import Optional

from .db import Conflict, NotFound, connect, now, prune
from .versions import insert_version, live_version

KINDS = ("setup", "edit")


def label(number: int) -> str:
    # Always prefixed: a pull request and an issue may share a counter, never a name.
    return f"PR #{number}"


def _event(kind: str, by: str, **more) -> dict:
    return {"type": kind, "by": by, "at": now(), **more}


def _to_record(row: sqlite3.Row, full: bool) -> dict:
    record = {
        "number": row["number"],
        "title": row["title"],
        "kind": row["kind"],
        "state": row["state"],
        "base_version": row["base_version"],
        "merged_version": row["merged_version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if full:
        record["config"] = json.loads(row["config"])
        record["layout"] = json.loads(row["layout"])
        record["events"] = json.loads(row["events"])
    return record


def _select(conn: sqlite3.Connection, agent_id: str, number: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM pulls WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    return _to_record(row, full=True) if row else None


def _require(conn: sqlite3.Connection, agent_id: str, number: int) -> dict:
    """The pull request, open. Raises NotFound or Conflict otherwise."""
    if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
        raise NotFound(f"No agent with id '{agent_id}'.")
    pull = _select(conn, agent_id, number)
    if pull is None:
        raise NotFound(f"The agent has no {label(number)}.")
    if pull["state"] != "open":
        raise Conflict(f"{label(number)} is {pull['state']}.")
    return pull


def _record_event(conn: sqlite3.Connection, agent_id: str, pull: dict, event: dict, **fields):
    """Update the pull request's `fields` and log `event`, touching the agent too."""
    fields["events"] = json.dumps([*pull["events"], event])
    fields["updated_at"] = event["at"]
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(
        f"UPDATE pulls SET {assignments} WHERE agent_id = ? AND number = ?",
        (*fields.values(), agent_id, pull["number"]),
    )
    conn.execute("UPDATE agents SET updated_at = ? WHERE id = ?", (event["at"], agent_id))


def insert_pull(
    conn: sqlite3.Connection,
    agent_id: str,
    title: str,
    kind: str,
    base_version: int,
    config: dict,
    layout: dict,
    by: str,
) -> dict:
    """Open a pull request holding `config`, numbered from the agent's counter. Returns it."""
    (number,) = conn.execute(
        "UPDATE agents SET next_number = next_number + 1 WHERE id = ? RETURNING next_number - 1",
        (agent_id,),
    ).fetchone()
    opened = _event("opened", by)
    conn.execute(
        "INSERT INTO pulls (agent_id, number, title, kind, state, base_version, merged_version,"
        " config, layout, events, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'open', ?, NULL, ?, ?, ?, ?, ?)",
        (
            agent_id,
            number,
            title,
            kind,
            base_version,
            json.dumps(config),
            json.dumps(prune(layout, config)),
            json.dumps([opened]),
            opened["at"],
            opened["at"],
        ),
    )
    return _select(conn, agent_id, number)


def list_pulls(agent_id: str, state: Optional[str] = None) -> list[dict]:
    """The agent's pull requests, newest first and without their copies; only those in `state`."""
    query = "SELECT * FROM pulls WHERE agent_id = ?"
    args: tuple = (agent_id,)
    if state is not None:
        query += " AND state = ?"
        args += (state,)
    with connect() as conn:
        rows = conn.execute(f"{query} ORDER BY number DESC", args).fetchall()
    return [_to_record(row, full=False) for row in rows]


def get_pull(agent_id: str, number: int) -> Optional[dict]:
    """The pull request with its copy of the agent and its events, or None."""
    with connect() as conn:
        return _select(conn, agent_id, number)


def open_pull(agent_id: str, title: str, kind: str, by: str) -> dict:
    """Open a pull request on a copy of the live version. Returns it.

    Raises NotFound for an unknown agent, Conflict if it is not live yet: until
    then, its changes go to pull request #1.
    """
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
            raise NotFound(f"No agent with id '{agent_id}'.")
        live = live_version(conn, agent_id)
        if live == 0:
            raise Conflict("The agent is not live yet: make changes on PR #1, then merge it.")
        version = conn.execute(
            "SELECT config, layout FROM versions WHERE agent_id = ? AND number = ?",
            (agent_id, live),
        ).fetchone()
        config, layout = json.loads(version["config"]), json.loads(version["layout"])
        return insert_pull(conn, agent_id, title, kind, live, config, layout, by)


def save_pull(agent_id: str, number: int, config: dict, layout: Optional[dict], by: str) -> dict:
    """Replace the pull request's copy with `config` and, if given, `layout`. Returns it.

    Without a layout the stored one is kept; either way, positions of nodes the
    new config does not have are dropped. Only an open pull request can be saved.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        if layout is None:
            layout = pull["layout"]
        _record_event(
            conn,
            agent_id,
            pull,
            _event("saved", by),
            config=json.dumps(config),
            layout=json.dumps(prune(layout, config)),
        )
        # Before it is live, the agent is what pull request #1 holds, name included.
        if pull["kind"] == "setup" and live_version(conn, agent_id) == 0:
            conn.execute("UPDATE agents SET name = ? WHERE id = ?", (config["name"], agent_id))
        return _select(conn, agent_id, number)


def merge_pull(agent_id: str, number: int, by: str) -> dict:
    """Make the pull request's copy the agent's next version, which goes live. Returns the PR.

    The caller checks first that the copy is a valid agent. Raises NotFound, or
    Conflict if the pull request is not open or live moved since it was based.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        live = live_version(conn, agent_id)
        if pull["base_version"] != live:
            based = f"v{pull['base_version']}" if pull["base_version"] else "no version"
            raise Conflict(
                f"{label(number)} is based on {based}, but live is now v{live}. "
                f"It has to be updated to v{live} before it can merge."
            )
        # One moment for both: the version is created when the PR is merged.
        merged = _event("merged", by)
        version = insert_version(
            conn, agent_id, pull["config"], pull["layout"], pull=number, at=merged["at"]
        )
        merged["version"] = version
        _record_event(
            conn,
            agent_id,
            pull,
            merged,
            state="merged",
            merged_version=version,
        )
        # The name lists show is the live one.
        conn.execute("UPDATE agents SET name = ? WHERE id = ?", (pull["config"]["name"], agent_id))
        return _select(conn, agent_id, number)


def close_pull(agent_id: str, number: int, by: str) -> dict:
    """Close the pull request without merging it. Returns it.

    Pull request #1 of an agent that is not live cannot be closed: it is the
    only way the agent can go live. Deleting the agent is the way to drop it.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        if pull["kind"] == "setup" and live_version(conn, agent_id) == 0:
            raise Conflict(
                f"{label(number)} is how the agent goes live, so it cannot be closed. "
                "Delete the agent instead."
            )
        _record_event(conn, agent_id, pull, _event("closed", by), state="closed")
        return _select(conn, agent_id, number)
