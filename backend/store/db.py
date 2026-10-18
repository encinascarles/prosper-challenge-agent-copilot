#
# The SQLite file and how the store modules open it.
#
# SQLite through the stdlib `sqlite3` module: a single-process app with a
# handful of agents needs no server and no ORM, and the file survives restarts.
#

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "agents.db"
DB_PATH_ENV = "AGENTS_DB_PATH"


class NotFound(LookupError):
    """There is no such agent, version or pull request. The message says which."""


class Conflict(ValueError):
    """The change cannot be made in the state things are in. The message says why."""


def db_path() -> Path:
    # Read on every call, not at import, so a test can point the store at a
    # temp file after this module is already loaded.
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


def now() -> str:
    # ISO 8601 in UTC: sorts as text and is what the browser's Date parses.
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the database for one operation, as one transaction.

    One short-lived connection per operation: FastAPI runs sync handlers in a
    thread pool and a sqlite3 connection must stay on the thread that opened it.
    The transaction is taken for writing from the start (`BEGIN IMMEDIATE`), so
    two requests cannot both read "live is v1" and both merge into v2. With a
    handful of users, serializing every operation costs nothing. Schema changes
    are inside the transaction too, so a migration that fails leaves nothing
    half done.
    """
    conn = sqlite3.connect(db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def prune(layout: dict, config: dict) -> dict:
    # Done by the store rather than by the caller so a config and its layout
    # cannot disagree, whoever writes: a save that removes a node also removes
    # its position, in the same write.
    names = {node["name"] for node in config["nodes"]}
    return {name: position for name, position in layout.items() if name in names}
