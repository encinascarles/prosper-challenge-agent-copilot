#
# Chats with Prosper AI — questions about an agent, asked outside any pull
# request.
#
# A chat is a short list of messages, kept as JSON in its row like a pull
# request's events: it is only ever read whole. It is titled by its first
# question. Each answer says what it was answered from (live "v2", or "PR #5"
# when the person asked from there), and may offer a pull request: a change
# the person asked for, with a one-line title and what it would change. A chat
# never changes the agent itself. Creating the offered pull request opens it
# on a copy of live, in the same write that marks the offer as taken, so an
# offer opens one pull request at most, however many times it is clicked.
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
    -- [{ by, at, text, about?, links?, offer?, failed? }]: what was said, in order
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
    offers = [m["offer"] for m in messages if m.get("offer")]
    record = {
        "id": row["id"],
        "title": row["title"],
        # The pull requests its offers opened, in order: what a list says of it.
        "pulls": [offer["pull"] for offer in offers if offer.get("pull")],
        "count": len(messages),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if full:
        record["messages"] = messages
        record["usage"] = json.loads(row["usage"])
    return record


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
    """Add `message` ({ by, text, … }) to the chat, and what it cost. Returns the chat."""
    with connect() as conn:
        row = _row(conn, agent_id, chat_id)
        message = {"at": now(), **message}
        messages = [*json.loads(row["messages"]), message]
        spent = json.loads(row["usage"])
        for key, value in (usage or {}).items():
            spent[key] = round(spent.get(key, 0) + value, 4)
        conn.execute(
            "UPDATE chats SET messages = ?, usage = ?, updated_at = ? WHERE id = ?",
            (json.dumps(messages), json.dumps(spent), message["at"], chat_id),
        )
        return _to_record(_row(conn, agent_id, chat_id), full=True)


def open_offer(agent_id: str, chat_id: int, index: int, work: dict) -> tuple[dict, dict]:
    """Open the pull request message `index` of the chat offers. Returns it, and the chat.

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
        asked = next(m for m in reversed(messages[:index]) if m["by"] == "you")
        request = {"type": "request", "by": "you", "at": asked["at"], "text": asked["text"]}
        chat = {"id": chat_id, "title": row["title"]}
        pull = _open_on_live(
            conn,
            agent_id,
            offer["title"],
            "change",
            "Prosper AI",
            request=request,
            prosper={**work, "request": {"text": asked["text"], "what": offer["what"]}},
            chat=chat,
        )
        offer["pull"] = pull["number"]
        conn.execute("UPDATE chats SET messages = ? WHERE id = ?", (json.dumps(messages), chat_id))
        return pull, _to_record(_row(conn, agent_id, chat_id), full=True)
