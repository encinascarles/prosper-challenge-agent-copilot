#
# Prosper AI's work on a pull request, as the store keeps it.
#
# A pull request Prosper AI works on carries a small JSON record next to its
# copy (the `prosper` column): its state ("working", "waiting" for an answer,
# "done" or "failed"), what it is doing now (the step a screen shows a spinner
# on), what it read (the guidelines, the source every rule quotes), the
# questions it asked and how many tokens it spent. What it does is logged in
# the pull request's events like anything else, signed "Prosper AI", so the
# conversation and the Build screen read it from the same place.
#
# A new agent built from guidelines starts here: its PR #1 is opened by Prosper
# AI on an empty copy, which the job (copilot/setup.py) then fills in.
#

import json
import sqlite3
from typing import Optional

from .agents import _insert_agent, select_agent
from .db import Conflict, connect, prune
from .pulls import PROSPER, _event, _record_event, _require, _select, insert_pull
from .suite import new_id, prune_rules


def _work(conn: sqlite3.Connection, agent_id: str, number: int) -> dict:
    row = conn.execute(
        "SELECT prosper FROM pulls WHERE agent_id = ? AND number = ?", (agent_id, number)
    ).fetchone()
    return json.loads(row["prosper"]) if row and row["prosper"] else {}


def _put(conn: sqlite3.Connection, agent_id: str, number: int, work: dict) -> None:
    conn.execute(
        "UPDATE pulls SET prosper = ? WHERE agent_id = ? AND number = ?",
        (json.dumps(work), agent_id, number),
    )


def create_setup(name: str, sources: list[dict], request: dict, read: str) -> tuple[dict, dict]:
    """A new agent whose PR #1 Prosper AI opens, empty, to build from `sources`. Returns both.

    `request` is the person's own event: what they asked for, with their notes
    and the files they attached. `read` is the first step, done as it opens:
    what it read.
    """
    config = {"name": name, "initial_node": "", "nodes": []}
    work = {"state": "working", "doing": "Drawing the steps", "sources": sources, "questions": []}
    with connect() as conn:
        agent_id = _insert_agent(conn, name)
        pull = insert_pull(
            conn,
            agent_id,
            f"Set up {name}",
            "setup",
            0,
            config,
            {},
            PROSPER,
            request=request,
            then=[_event("step", PROSPER, text=read)],
            prosper=work,
        )
        return select_agent(conn, agent_id), pull


def work_of(agent_id: str, number: int) -> dict:
    """Prosper AI's whole record of its work on the pull request, sources included."""
    with connect() as conn:
        return _work(conn, agent_id, number)


def set_state(agent_id: str, number: int, state: str, doing: Optional[str] = None) -> dict:
    """Say what Prosper AI is up to on the pull request. Returns it."""
    with connect() as conn:
        work = _work(conn, agent_id, number)
        work.update(state=state, doing=doing)
        _put(conn, agent_id, number, work)
        return _select(conn, agent_id, number)


def spend(agent_id: str, number: int, usage: dict) -> None:
    """Add `usage` (requests, tokens, USD) to what Prosper AI spent on the pull request."""
    with connect() as conn:
        work = _work(conn, agent_id, number)
        spent = work.get("usage") or {}
        work["usage"] = {key: round(spent.get(key, 0) + value, 4) for key, value in usage.items()}
        _put(conn, agent_id, number, work)


def write(
    agent_id: str,
    number: int,
    event: dict,
    config: Optional[dict] = None,
    rules: tuple = (),
    tests: tuple = (),
    state: Optional[str] = None,
    doing: Optional[str] = None,
) -> dict:
    """Prosper AI changes the pull request's copy and logs `event`, in one write. Returns it.

    `config` replaces the agent when given (positions and rules of steps it no
    longer has go with them); `rules` and `tests` are added, each given an id.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by=PROSPER)
        fields: dict = {}
        current = pull["config"]
        if config is not None:
            current = config
            fields["config"] = json.dumps(config)
            fields["layout"] = json.dumps(prune(pull["layout"], config))
        kept = prune_rules(pull["rules"], current)
        added = [{"id": new_id(), **rule} for rule in rules]
        if config is not None or rules:
            fields["rules"] = json.dumps(prune_rules([*kept, *added], current))
        if tests:
            fields["tests"] = json.dumps([*pull["tests"], *({"id": new_id(), **t} for t in tests)])
        _record_event(conn, agent_id, pull, event, **fields)
        if config is not None and pull["kind"] == "setup":
            conn.execute("UPDATE agents SET name = ? WHERE id = ?", (config["name"], agent_id))
        if state is not None:
            work = _work(conn, agent_id, number)
            work.update(state=state, doing=doing)
            _put(conn, agent_id, number, work)
        return _select(conn, agent_id, number)


def log(agent_id: str, number: int, event: dict) -> dict:
    """Add `event` to the pull request's conversation. Returns it."""
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        _record_event(conn, agent_id, pull, event)
        return _select(conn, agent_id, number)


def ask(agent_id: str, number: int, questions: list[dict]) -> dict:
    """Ask the person `questions`, each { text, options: [{ label, rule }] }. Returns the PR.

    Each is logged as one event with its options; the rule each option becomes
    stays in the store until it is picked. Prosper AI then waits.
    """
    with connect() as conn:
        _require(conn, agent_id, number)
        work = _work(conn, agent_id, number)
        for question in questions:
            asked = {"id": new_id(), **question, "answer": None}
            work["questions"] = [*work.get("questions", []), asked]
            event = _event(
                "question",
                PROSPER,
                question=asked["id"],
                text=question["text"],
                options=[option["label"] for option in question["options"]],
            )
            _record_event(conn, agent_id, _select(conn, agent_id, number), event)
        work.update(state="waiting", doing=None)
        _put(conn, agent_id, number, work)
        return _select(conn, agent_id, number)


def _open_question(work: dict, question: Optional[str]) -> dict:
    waiting = [q for q in work.get("questions", []) if q["answer"] is None]
    if question is None:
        if not waiting:
            raise Conflict("Prosper AI is not waiting for an answer.")
        return waiting[0]
    found = next((q for q in work.get("questions", []) if q["id"] == question), None)
    if found is None:
        raise Conflict("Prosper AI asked no such question.")
    if found["answer"] is not None:
        raise Conflict("That question has its answer already.")
    return found


def pick(agent_id: str, number: int, question: str, option: int) -> tuple[dict, bool]:
    """The person picks option `option` of `question`: its rule goes into the copy.

    Returns the pull request and whether every question has its answer now.
    The rule's source is the answer, in this pull request. Refused while
    Prosper AI works (on an answer written to another question, say): the
    job would write over it, and checks could start halfway through.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by="you")
        work = _work(conn, agent_id, number)
        asked = _open_question(work, question)
        if not 0 <= option < len(asked["options"]):
            raise Conflict(f"That question has no option {option + 1}.")
        chosen = asked["options"][option]
        asked["answer"] = chosen["label"]
        rule = {
            "id": new_id(),
            "step": chosen["rule"]["step"],
            "text": chosen["rule"]["text"],
            "source": {"kind": "answer", "pull": number, "quote": chosen["label"]},
        }
        done = all(q["answer"] is not None for q in work["questions"])
        work.update(state="done" if done else "waiting", doing=None)
        _put(conn, agent_id, number, work)
        answered = _event("answer", "you", question=question, text=chosen["label"])
        _record_event(conn, agent_id, pull, answered)
        pull = _select(conn, agent_id, number)
        added = _event("rule", PROSPER, step=rule["step"], text=rule["text"])
        rules = prune_rules([*pull["rules"], rule], pull["config"])
        _record_event(conn, agent_id, pull, added, rules=json.dumps(rules))
        return _select(conn, agent_id, number), done


def take_message(agent_id: str, number: int, text: str) -> tuple[dict, Optional[dict]]:
    """Log the person's message to Prosper AI, which starts working on it. Returns the PR.

    While Prosper AI waits for an answer, the message is the answer to its
    first open question: returned with it, so the job knows what it answers.
    Refused while Prosper AI is still working on something else.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by="you")
        work = _work(conn, agent_id, number)
        answers = None
        if work.get("state") == "waiting":
            answers = _open_question(work, None)
            answers["answer"] = text
            event = _event("answer", "you", question=answers["id"], text=text)
        else:
            event = _event("message", "you", text=text)
        work.update(state="working", doing="Working on it")
        _put(conn, agent_id, number, work)
        _record_event(conn, agent_id, pull, event)
        return _select(conn, agent_id, number), answers


def waiting_for(agent_id: str, number: int) -> list[dict]:
    """The questions Prosper AI asked on the pull request that have no answer yet."""
    return [q for q in work_of(agent_id, number).get("questions", []) if q["answer"] is None]
