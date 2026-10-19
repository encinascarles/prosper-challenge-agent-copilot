#
# Chats with Prosper AI — questions about an agent, asked outside any pull
# request.
#
# A chat is a short list of messages, kept as JSON in its row like a pull
# request's events: it is only ever read whole. It is titled by its first
# question. Each answer says what it was answered from (live "v2", or "PR #5"
# when the person asked from there).
#
# Prosper AI's message may carry an action it proposes (open an issue, merge
# a pull request): a card that waits for the person. Taking the card claims it
# in one write (pending -> running), so a double click does it once; then it
# is done, failed (with the sentence that refused it) or declined. A card left
# pending when the person writes again is skipped: they moved on, and what it
# proposed was about the chat as it was. Older chats may carry an offer
# instead (a pull request the change opens): opening it marks it taken in the
# same write.
#

import json
import sqlite3
from typing import Optional

from .db import Conflict, NotFound, connect, now
from .pulls import _open_on_live

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    title TEXT NOT NULL,  -- its first question
    -- [{ by, at, text, about?, links?, reads?, action?, offer?, failed? }]: what was said
    messages TEXT NOT NULL DEFAULT '[]',
    usage TEXT NOT NULL DEFAULT '{}',  -- what Prosper AI's answers cost: requests, tokens, USD
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

MAX_TITLE_CHARS = 80


def title_of(text: str) -> str:
    """A chat's title: its first question, on one line, cut at a word if it is long."""
    line = " ".join(text.split())
    if len(line) <= MAX_TITLE_CHARS:
        return line
    return line[: MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0] + "…"


def _to_record(row: sqlite3.Row, full: bool) -> dict:
    messages = json.loads(row["messages"])
    record = {
        "id": row["id"],
        "title": row["title"],
        # The pull requests it opened, in order: what a list says of it.
        "pulls": [number for m in messages if (number := _opened(m))],
        "count": len(messages),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if full:
        record["messages"] = messages
        record["usage"] = json.loads(row["usage"])
    return record


# The actions that open a pull request.
_OPENING = ("open_pull_request", "fix_issue")


def _opened(message: dict) -> Optional[int]:
    """The pull request the message opened: by an action, or an older chat's offer."""
    if message.get("offer"):
        return message["offer"].get("pull")
    action = message.get("action") or {}
    if action.get("tool") in _OPENING and action["state"] == "done":
        return action["result"]["link"]["number"]
    return None


def _require_agent(conn: sqlite3.Connection, agent_id: str) -> None:
    if not conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
        raise NotFound(f"No agent with id '{agent_id}'.")


def _row(conn: sqlite3.Connection, agent_id: str, chat_id: int) -> sqlite3.Row:
    _require_agent(conn, agent_id)
    row = conn.execute(
        "SELECT * FROM chats WHERE agent_id = ? AND id = ?", (agent_id, chat_id)
    ).fetchone()
    if row is None:
        raise NotFound(f"The agent has no chat {chat_id}.")
    return row


def create_chat(agent_id: str, text: str) -> dict:
    """A new chat, titled by `text`, its first question. Returns it, with that question."""
    at = now()
    with connect() as conn:
        _require_agent(conn, agent_id)
        message = {"by": "you", "at": at, "text": text}
        (chat_id,) = conn.execute(
            "INSERT INTO chats (agent_id, title, messages, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?) RETURNING id",
            (agent_id, title_of(text), json.dumps([message]), at, at),
        ).fetchone()
        return _to_record(_row(conn, agent_id, chat_id), full=True)


def list_chats(agent_id: str) -> list[dict]:
    """The agent's chats, the latest one written in first, without their messages."""
    with connect() as conn:
        _require_agent(conn, agent_id)
        rows = conn.execute(
            "SELECT * FROM chats WHERE agent_id = ? ORDER BY updated_at DESC, id DESC",
            (agent_id,),
        ).fetchall()
        return [_to_record(row, full=False) for row in rows]


def get_chat(agent_id: str, chat_id: int) -> dict:
    """The chat with its messages. Raises NotFound."""
    with connect() as conn:
        return _to_record(_row(conn, agent_id, chat_id), full=True)


def add_message(agent_id: str, chat_id: int, message: dict, usage: Optional[dict] = None) -> dict:
    """Add `message` ({ by, text, … }) to the chat, and what it cost. Returns the chat.

    The person's message skips the actions still waiting for them.
    """
    with connect() as conn:
        row = _row(conn, agent_id, chat_id)
        message = {"at": now(), **message}
        messages = json.loads(row["messages"])
        if message["by"] == "you":
            for earlier in messages:
                if (earlier.get("action") or {}).get("state") == "pending":
                    earlier["action"]["state"] = "skipped"
                    earlier.pop("resume", None)
        messages.append(message)
        spent = json.loads(row["usage"])
        for key, value in (usage or {}).items():
            spent[key] = round(spent.get(key, 0) + value, 4)
        conn.execute(
            "UPDATE chats SET messages = ?, usage = ?, updated_at = ? WHERE id = ?",
            (json.dumps(messages), json.dumps(spent), message["at"], chat_id),
        )
        return _to_record(_row(conn, agent_id, chat_id), full=True)


def claim_action(agent_id: str, chat_id: int, index: int, do: bool) -> dict:
    """Take (`do`) or decline the action message `index` proposes. Returns the message.

    Raises NotFound, or Conflict when it proposes nothing or was decided already.
    """
    with connect() as conn:
        row = _row(conn, agent_id, chat_id)
        messages = json.loads(row["messages"])
        if not 0 <= index < len(messages) or not messages[index].get("action"):
            raise Conflict("That message proposes nothing to do.")
        message = messages[index]
        state = message["action"]["state"]
        if state != "pending":
            raise Conflict(f"That was {_DECIDED.get(state, state)} already.")
        message["action"]["state"] = "running" if do else "declined"
        if not do:
            message.pop("resume", None)
        conn.execute("UPDATE chats SET messages = ? WHERE id = ?", (json.dumps(messages), chat_id))
        return message


_DECIDED = {"running": "being done", "skipped": "left behind"}


def settle_action(
    agent_id: str, chat_id: int, index: int, result: Optional[dict], error: Optional[str]
) -> dict:
    """Write how the action message `index` went: its `result` ({ text, link }), or the
    `error` that refused it. Returns the chat."""
    with connect() as conn:
        row = _row(conn, agent_id, chat_id)
        messages = json.loads(row["messages"])
        message = messages[index]
        message["action"]["state"] = "failed" if error else "done"
        message["action"]["result"] = result
        message["action"]["error"] = error
        message.pop("resume", None)
        conn.execute(
            "UPDATE chats SET messages = ?, updated_at = ? WHERE id = ?",
            (json.dumps(messages), now(), chat_id),
        )
        return _to_record(_row(conn, agent_id, chat_id), full=True)


INTERRUPTED = "Interrupted: the server stopped while it was being done. Check, and ask again."


def stop_unfinished(conn: sqlite3.Connection) -> None:
    """Mark as failed the actions a stopped server left being done.

    Done in the server's process, so after a restart nothing is doing them;
    left "running", they could be neither retried nor cancelled. Whether the
    act itself happened is not known: the card says to check.
    """
    rows = conn.execute("SELECT id, messages FROM chats WHERE messages LIKE '%\"running\"%'")
    for row in rows.fetchall():
        messages = json.loads(row["messages"])
        stopped = False
        for message in messages:
            action = message.get("action") or {}
            if action.get("state") == "running":
                action.update(state="failed", error=INTERRUPTED)
                message.pop("resume", None)
                stopped = True
        if stopped:
            conn.execute(
                "UPDATE chats SET messages = ? WHERE id = ?", (json.dumps(messages), row["id"])
            )


def open_change(agent_id: str, chat_id: int, index: int, title: str, what: str, work: dict) -> dict:
    """Open a pull request of kind "change" for what the chat asked, up to message `index`.

    Prosper AI opens it on a copy of live, with `work` as its record, and
    starts from the person's own words: their latest message before `index`.
    Raises NotFound, or Conflict when the agent is not live.
    """
    with connect() as conn:
        row = _row(conn, agent_id, chat_id)
        return _open_change(
            conn, agent_id, row, json.loads(row["messages"]), index, title, what, work
        )


def _open_change(
    conn: sqlite3.Connection,
    agent_id: str,
    row: sqlite3.Row,
    messages: list[dict],
    index: int,
    title: str,
    what: str,
    work: dict,
) -> dict:
    asked = next(m for m in reversed(messages[:index]) if m["by"] == "you")
    request = {"type": "request", "by": "you", "at": asked["at"], "text": asked["text"]}
    return _open_on_live(
        conn,
        agent_id,
        title,
        "change",
        "Prosper AI",
        request=request,
        prosper={**work, "request": {"text": asked["text"], "what": what}},
        chat={"id": row["id"], "title": row["title"]},
    )


def open_offer(agent_id: str, chat_id: int, index: int, work: dict) -> tuple[dict, dict]:
    """Open the pull request message `index` of an older chat offers. Returns it, and the chat.

    Prosper AI opens it on a copy of live, with `work` as its record, and
    starts from the person's own words: the message the offer answered. Raises
    NotFound, or Conflict when the message offers nothing, its pull request is
    open already, or the agent is not live.
    """
    with connect() as conn:
        row = _row(conn, agent_id, chat_id)
        messages = json.loads(row["messages"])
        if not 0 <= index < len(messages) or not messages[index].get("offer"):
            raise Conflict("That message offers no pull request.")
        offer = messages[index]["offer"]
        if offer.get("pull"):
            raise Conflict(f"PR #{offer['pull']} is open for it already.")
        pull = _open_change(
            conn, agent_id, row, messages, index, offer["title"], offer["what"], work
        )
        offer["pull"] = pull["number"]
        conn.execute("UPDATE chats SET messages = ? WHERE id = ?", (json.dumps(messages), chat_id))
        return pull, _to_record(_row(conn, agent_id, chat_id), full=True)
