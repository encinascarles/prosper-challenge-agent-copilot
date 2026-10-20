#
# Pull requests — proposed changes to an agent, each on its own copy of it.
#
# Nothing reaches callers except by merging one. A pull request is based on the
# version that was live when it was opened and holds its own copy of the agent
# (config and layout), which is what the editor saves to. Merging turns that
# copy into the next version. A new agent starts with pull request #1, "Set up
# <name>", based on nothing: the agent goes live when it is merged.
#
# A pull request is open, merged or closed; a closed one can be reopened. Its
# small event log (opened, saved, merged, closed, reopened, updated: by whom and
# when) is kept in the row as JSON: it is only ever read with the pull request
# it belongs to.
#
# A copy is the agent's config and layout, and its rules and tests (suite.py).
# Rules and tests are added and taken out one at a time, each an event; every
# change to a copy starts its checks again (runs.py), and a merge is refused
# until they pass: what goes live has passed the agent's whole suite.
#
# A fix is a pull request that points at the issue it fixes (issues.py): it is
# opened from the issue, closing or reopening it is logged there too, and
# merging it resolves the issue in the same write as the new version. A change
# is one the person asked Prosper AI for in a chat (chats.py): it names the chat
# it came from.
#
# Prosper AI can work on a pull request (prosper.py): while it does, the
# person's own changes to that copy are refused, or the two would write over
# each other, and so is a merge, until Prosper AI is done and has its answers.
#
# Merging is refused once live has moved past the version the pull request was
# based on: its copy was made from an older agent, and merging it would quietly
# undo whatever was merged in between. Updating it replaces its copy with its
# changes replayed on the live version, which becomes its new base.
#

import json
import sqlite3
from typing import Optional

from . import issues, runs
from .db import Conflict, NotFound, connect, now, prune
from .suite import added_in, fingerprint, manual, new_id, prune_rules, rebase, rename_rules
from .versions import insert_version, live_version

KINDS = ("setup", "edit", "fix", "change")
# Who Prosper AI is in a pull request's log.
PROSPER = "Prosper AI"


def label(number: int) -> str:
    # Always prefixed: a pull request and an issue may share a counter, never a name.
    return f"PR #{number}"


def _event(kind: str, by: str, **more) -> dict:
    return {"type": kind, "by": by, "at": now(), **more}


def _to_record(conn: sqlite3.Connection, row: sqlite3.Row, full: bool) -> dict:
    record = {
        "number": row["number"],
        "title": row["title"],
        "kind": row["kind"],
        "state": row["state"],
        "base_version": row["base_version"],
        "merged_version": row["merged_version"],
        "fixes": row["fixes"],
        "chat": json.loads(row["chat"]) if row["chat"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "checks": _checks(conn, row),
        "prosper": _public(row["prosper"]),
    }
    if full:
        record["config"] = json.loads(row["config"])
        record["layout"] = json.loads(row["layout"])
        record["rules"] = json.loads(row["rules"])
        record["tests"] = json.loads(row["tests"])
        record["events"] = json.loads(row["events"])
    return record


def _public(work: Optional[str]) -> Optional[dict]:
    # What screens show of Prosper AI's work. What it read stays in the store.
    if work is None:
        return None
    work = json.loads(work)
    return {key: work.get(key) for key in ("state", "doing", "usage")}


def busy(pull: dict, merging: bool = False) -> Optional[str]:
    """Why Prosper AI's work on `pull` stops a change by someone else (or a merge), or None."""
    state = (pull.get("prosper") or {}).get("state")
    if state == "working":
        return f"Prosper AI is still working on {label(pull['number'])}."
    if merging and state == "waiting":
        return f"Prosper AI needs your answer in {label(pull['number'])} first."
    return None


def _checks(conn: sqlite3.Connection, row: sqlite3.Row) -> Optional[dict]:
    # Only a run on the copy as it is now says anything about it.
    run = runs.select_run(conn, row["agent_id"], pull=row["number"])
    copy = {key: json.loads(row[key]) for key in ("config", "rules", "tests")}
    return runs.summary(run) if runs.is_of(run, fingerprint(copy)) else None


def _select(conn: sqlite3.Connection, agent_id: str, number: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM pulls WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    return _to_record(conn, row, full=True) if row else None


def _require(
    conn: sqlite3.Connection,
    agent_id: str,
    number: int,
    state: str = "open",
    by: Optional[str] = None,
) -> dict:
    """The pull request, in `state`. Raises NotFound or Conflict otherwise.

    With `by`, a change is about to be made by them: refused while Prosper AI
    works on it, unless they are Prosper AI.
    """
    if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
        raise NotFound(f"No agent with id '{agent_id}'.")
    pull = _select(conn, agent_id, number)
    if pull is None:
        raise NotFound(f"The agent has no {label(number)}.")
    if pull["state"] != state:
        raise Conflict(f"{label(number)} is {pull['state']}.")
    if by is not None and by != PROSPER and (reason := busy(pull)):
        raise Conflict(reason)
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
    rules: Optional[list] = None,
    tests: Optional[list] = None,
    request: Optional[dict] = None,
    then: Optional[list] = None,
    prosper: Optional[dict] = None,
    fixes: Optional[int] = None,
    chat: Optional[dict] = None,
) -> dict:
    """Open a pull request holding `config`, numbered from the agent's counter. Returns it.

    When Prosper AI opens it: `request` is what it was asked, logged before it
    opened it, `then` what it did next, and `prosper` its work on it. A fix
    names the issue it `fixes`; a change, the `chat` ({ id, title }) it was asked in.
    """
    (number,) = conn.execute(
        "UPDATE agents SET next_number = next_number + 1 WHERE id = ? RETURNING next_number - 1",
        (agent_id,),
    ).fetchone()
    # The version it was opened on: its base may move later, with an update.
    opened = _event(
        "opened",
        by,
        **({"version": base_version} if base_version else {}),
        **({"issue": fixes} if fixes else {}),
        **({"chat": chat["id"]} if chat else {}),
    )
    conn.execute(
        "INSERT INTO pulls (agent_id, number, title, kind, state, base_version, merged_version,"
        " config, layout, rules, tests, events, prosper, fixes, chat, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'open', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            agent_id,
            number,
            title,
            kind,
            base_version,
            json.dumps(config),
            json.dumps(prune(layout, config)),
            json.dumps(prune_rules(rules or [], config)),
            json.dumps(tests or []),
            json.dumps([*([request] if request else []), opened, *(then or [])]),
            None if prosper is None else json.dumps(prosper),
            fixes,
            None if chat is None else json.dumps(chat),
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
        return [_to_record(conn, row, full=False) for row in rows]


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
        return _open_on_live(conn, agent_id, title, kind, by)


def _open_on_live(conn: sqlite3.Connection, agent_id: str, title: str, kind: str, by: str, **more):
    if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
        raise NotFound(f"No agent with id '{agent_id}'.")
    live = live_version(conn, agent_id)
    if live == 0:
        raise Conflict("The agent is not live yet: make changes on PR #1, then merge it.")
    version = conn.execute(
        "SELECT * FROM versions WHERE agent_id = ? AND number = ?", (agent_id, live)
    ).fetchone()
    return insert_pull(
        conn,
        agent_id,
        title,
        kind,
        live,
        json.loads(version["config"]),
        json.loads(version["layout"]),
        by,
        json.loads(version["rules"]),
        json.loads(version["tests"]),
        **more,
    )


def open_fix(agent_id: str, issue: int, by: str, prosper: Optional[dict] = None) -> dict:
    """Open a pull request on a copy of live that fixes `issue`: "Fix: <its title>". Returns it.

    With `prosper`, Prosper AI opens it and works on it. Raises NotFound, or
    Conflict when the issue is resolved, ignored or already being fixed, or
    the agent is not live.
    """
    with connect() as conn:
        found = issues.check_fixable(conn, agent_id, issue)
        pull = _open_on_live(
            conn, agent_id, f"Fix: {found['title']}", "fix", by, prosper=prosper, fixes=issue
        )
        issues.log_fix(conn, agent_id, issue, "fixing", pull["number"], by)
        return pull


def save_pull(
    agent_id: str,
    number: int,
    config: dict,
    layout: Optional[dict],
    by: str,
    summary: Optional[str] = None,
    renames: Optional[dict] = None,
) -> dict:
    """Replace the pull request's copy with `config` and, if given, `layout`. Returns it.

    Without a layout the stored one is kept; either way, positions of nodes the
    new config does not have are dropped. Only an open pull request can be saved.
    `summary`, one line on what the save changed, goes in its event. `renames`,
    { old name: new name }, are the steps the save renamed: their rules follow
    them. Rules for steps that are gone are dropped.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by=by)
        if layout is None:
            layout = pull["layout"]
        rules = prune_rules(rename_rules(pull["rules"], renames or {}), config)
        _record_event(
            conn,
            agent_id,
            pull,
            _event("saved", by, **({"summary": summary} if summary else {})),
            config=json.dumps(config),
            layout=json.dumps(prune(layout, config)),
            rules=json.dumps(rules),
        )
        # Before it is live, the agent is what pull request #1 holds, name included.
        if pull["kind"] == "setup" and live_version(conn, agent_id) == 0:
            conn.execute("UPDATE agents SET name = ? WHERE id = ?", (config["name"], agent_id))
        return _select(conn, agent_id, number)


def merge_pull(agent_id: str, number: int, by: str) -> dict:
    """Make the pull request's copy the agent's next version, which goes live. Returns the PR.

    The caller checks first that the copy is a valid agent. Raises NotFound, or
    Conflict if the pull request is not open, live moved since it was based or
    its checks do not pass.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        if reason := _merge_refusal(conn, agent_id, pull):
            raise Conflict(reason)
        run = runs.select_run(conn, agent_id, pull=number)
        # One moment for both: the version is created when the PR is merged.
        merged = _event("merged", by)
        version = insert_version(
            conn,
            agent_id,
            pull["config"],
            pull["layout"],
            pull=number,
            at=merged["at"],
            rules=pull["rules"],
            tests=pull["tests"],
        )
        merged["version"] = version
        # Its checks ran on this very copy: they are the version's too.
        conn.execute("UPDATE runs SET version = ? WHERE id = ?", (version, run["id"]))
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
        if pull["fixes"]:
            issues.resolve_by_fix(conn, agent_id, pull["fixes"], number, version, by)
        return _select(conn, agent_id, number)


def merge_refusal(agent_id: str, number: int) -> Optional[str]:
    """Why the pull request cannot merge now, in the words a merge would be refused with,
    or None if it can. Raises NotFound, or Conflict when it is not open."""
    with connect() as conn:
        return _merge_refusal(conn, agent_id, _require(conn, agent_id, number))


def _merge_refusal(conn: sqlite3.Connection, agent_id: str, pull: dict) -> Optional[str]:
    number = pull["number"]
    if reason := busy(pull, merging=True):
        return reason
    live = live_version(conn, agent_id)
    if pull["base_version"] != live:
        based = f"v{pull['base_version']}" if pull["base_version"] else "no version"
        return (
            f"{label(number)} is based on {based}, but live is now v{live}. "
            f"It has to be updated to v{live} before it can merge."
        )
    run = runs.select_run(conn, agent_id, pull=number)
    if blocker := runs.merge_blocker(run, fingerprint(pull)):
        return f"{label(number)} cannot merge: {blocker[0].lower()}{blocker[1:]}"
    return None


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
        if pull["fixes"]:
            issues.log_fix(conn, agent_id, pull["fixes"], "unlinked", number, by)
        return _select(conn, agent_id, number)


def reopen_pull(agent_id: str, number: int, by: str) -> dict:
    """Open a closed pull request again, as it was. Returns it.

    Its base stays what it was: if live moved on meanwhile, it needs an update
    before it can merge, like any other pull request left behind. A fix is
    refused once its issue is resolved, ignored or fixed by another one.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, state="closed")
        if pull["fixes"]:
            # One fix of an issue at a time, as when it is opened.
            issues.check_fixable(conn, agent_id, pull["fixes"])
        _record_event(conn, agent_id, pull, _event("reopened", by), state="open")
        if pull["fixes"]:
            issues.log_fix(conn, agent_id, pull["fixes"], "relinked", number, by)
        return _select(conn, agent_id, number)


def rename_pull(agent_id: str, number: int, title: str) -> dict:
    """Give an open pull request another title. Returns it.

    Not an event: the title is how people find it, not a change to the agent.
    """
    with connect() as conn:
        _require(conn, agent_id, number)
        conn.execute(
            "UPDATE pulls SET title = ? WHERE agent_id = ? AND number = ?",
            (title, agent_id, number),
        )
        return _select(conn, agent_id, number)


def update_pull(
    agent_id: str,
    number: int,
    config: dict,
    layout: dict,
    onto: int,
    by: str,
    summary: Optional[str] = None,
) -> dict:
    """Base the pull request on live `onto`, with `config` as its copy. Returns it.

    `config` is the pull request's changes replayed on version `onto`, which the
    caller worked out (and checked is a valid agent). Its rules and tests are
    replayed here: those of `onto`, then the ones the pull request added. It is taken only if `onto`
    is still live: a merge in between would make it a replay on the wrong
    version. Raises NotFound, or Conflict when not open, already on live, or
    live is no longer `onto`.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        live = live_version(conn, agent_id)
        if pull["base_version"] == live:
            raise Conflict(f"{label(number)} is already based on v{live}.")
        if onto != live:
            raise Conflict(f"Live is v{live} now, not v{onto}. Update it again.")
        updated = _event("updated", by, version=live, **({"summary": summary} if summary else {}))
        onto_row = conn.execute(
            "SELECT rules, tests FROM versions WHERE agent_id = ? AND number = ?", (agent_id, live)
        ).fetchone()
        own = {kind: [i for i in pull[kind] if added_in(i, number)] for kind in ("rules", "tests")}
        rules = prune_rules(rebase(own["rules"], json.loads(onto_row["rules"])), config)
        _record_event(
            conn,
            agent_id,
            pull,
            updated,
            base_version=live,
            config=json.dumps(config),
            layout=json.dumps(prune(layout, config)),
            rules=json.dumps(rules),
            tests=json.dumps(rebase(own["tests"], json.loads(onto_row["tests"]))),
        )
        return _select(conn, agent_id, number)


def add_rule(agent_id: str, number: int, step: Optional[str], text: str, by: str) -> dict:
    """Add a rule to the pull request's copy, for `step` or (None) every step. Returns the PR.

    Raises Conflict if `step` is not a step of its copy.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by=by)
        if step is not None and step not in {node["name"] for node in pull["config"]["nodes"]}:
            raise Conflict(f"There is no step '{step}' in {label(number)}.")
        rule = {"id": new_id(), "step": step, "text": text, "source": manual(number)}
        _record_event(
            conn,
            agent_id,
            pull,
            _event("rule", by, step=step, text=text),
            rules=json.dumps([*pull["rules"], rule]),
        )
        return _select(conn, agent_id, number)


def add_test(agent_id: str, number: int, test: dict, by: str) -> dict:
    """Add a test, { name, caller, checks }, to the pull request's copy. Returns the PR."""
    with connect() as conn:
        pull = _require(conn, agent_id, number, by=by)
        test = {"id": new_id(), **test, "source": manual(number)}
        _record_event(
            conn,
            agent_id,
            pull,
            _event("test", by, text=test["name"]),
            tests=json.dumps([*pull["tests"], test]),
        )
        return _select(conn, agent_id, number)


def take_out(agent_id: str, number: int, kind: str, item_id: str, by: str) -> dict:
    """Take the rule or test (`kind`: "rules" or "tests") out of the pull request. Returns it.

    Only one added in this pull request: the others are live already, and
    taking them out is not what a pull request that only adds can replay.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by=by)
        item = next((i for i in pull[kind] if i["id"] == item_id), None)
        what = "rule" if kind == "rules" else "test"
        if item is None:
            raise NotFound(f"{label(number)} has no {what} '{item_id}'.")
        if not added_in(item, number):
            raise Conflict(f"That {what} was not added in {label(number)}.")
        text = item["text"] if kind == "rules" else item["name"]
        details = {"step": item["step"]} if kind == "rules" else {}
        _record_event(
            conn,
            agent_id,
            pull,
            _event(what, by, text=text, removed=True, **details),
            **{kind: json.dumps([i for i in pull[kind] if i["id"] != item_id])},
        )
        return _select(conn, agent_id, number)


def stop_prosper(conn: sqlite3.Connection) -> None:
    """Mark as interrupted the Prosper AI work a stopped server left going.

    Its jobs run in the server's process, so after a restart nothing is doing
    that work any more; left "working", it would refuse every change and the
    merge for good. "failed" is the state a message to Prosper AI retries from.
    """
    rows = conn.execute(
        "SELECT agent_id, number, prosper FROM pulls WHERE prosper IS NOT NULL AND state = 'open'"
    ).fetchall()
    for row in rows:
        work = json.loads(row["prosper"])
        if work.get("state") != "working":
            continue
        work.update(state="failed", doing=None)
        conn.execute(
            "UPDATE pulls SET prosper = ? WHERE agent_id = ? AND number = ?",
            (json.dumps(work), row["agent_id"], row["number"]),
        )
        pull = _select(conn, row["agent_id"], row["number"])
        _record_event(conn, row["agent_id"], pull, _event("interrupted", PROSPER))


def record_checks(agent_id: str, number: int, run: dict) -> None:
    """Log in the pull request how its finished checks went."""
    checks = runs.summary(run)
    with connect() as conn:
        pull = _select(conn, agent_id, number)
        if pull is None or checks is None:
            return
        counts = {key: checks[key] for key in ("passed", "flaky", "total")}
        _record_event(conn, agent_id, pull, _event("checks", "checks", **counts))
