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
# AI on an empty copy, which Prosper AI (copilot/agent.py) then fills in.
#
# Prosper AI changes the copy in small pieces (a step's task, a rule, a test).
# Each is written at once, so a restart loses none, but said in the
# conversation only when Prosper AI says why: the change's lines and its rule
# and test events wait in the record, and go under its next message as one
# turn ("Added a rule in Offer times · Changed when Greeting moves on").
# While it draws a new agent, each piece is said as a step at once instead
# ("Drew 6 steps"), for the person watching it build.
#

import json
import sqlite3
from typing import Optional

from .agents import _insert_agent, select_agent
from .db import Conflict, connect, now, prune
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
    work = {
        "state": "working",
        "doing": "Reading your guidelines",
        "sources": sources,
        "questions": [],
    }
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


def mark_built(agent_id: str, number: int, step: str) -> None:
    """Record that Prosper AI's work got past `step` ("asked", "reproduced"): its guards read it."""
    with connect() as conn:
        work = _work(conn, agent_id, number)
        work["built"] = [*work.get("built", []), step]
        _put(conn, agent_id, number, work)


def update(agent_id: str, number: int, **fields) -> None:
    """Set `fields` in Prosper AI's record of its work on the pull request."""
    with connect() as conn:
        work = _work(conn, agent_id, number)
        work.update(fields)
        _put(conn, agent_id, number, work)


def change(
    agent_id: str,
    number: int,
    line: Optional[str],
    config: Optional[dict] = None,
    rules: Optional[list] = None,
    tests: Optional[list] = None,
    events: tuple = (),
    step: Optional[dict] = None,
) -> dict:
    """Prosper AI changes the copy: `config`, and its `rules` and `tests` whole, when given.

    With `step`, the change is said at once, as that event. Otherwise `line`
    (what changed, in a few words, or None) and the rule and test `events` wait
    for Prosper AI's next message (`say`). Rules of steps that are gone go.
    Returns the pull request.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by=PROSPER)
        current = config if config is not None else pull["config"]
        fields: dict = {}
        if config is not None:
            fields["config"] = json.dumps(config)
            fields["layout"] = json.dumps(prune(pull["layout"], config))
        if config is not None or rules is not None:
            fields["rules"] = json.dumps(
                prune_rules(pull["rules"] if rules is None else rules, current)
            )
        if tests is not None:
            fields["tests"] = json.dumps(tests)
        if step is not None:
            _record_event(conn, agent_id, pull, step, **fields)
            return _select(conn, agent_id, number)
        fields["updated_at"] = now()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        conn.execute(
            f"UPDATE pulls SET {assignments} WHERE agent_id = ? AND number = ?",
            (*fields.values(), agent_id, number),
        )
        work = _work(conn, agent_id, number)
        pending = work.get("pending") or {"lines": [], "events": []}
        if line and line not in pending["lines"]:
            pending["lines"].append(line)
        pending["events"] += list(events)
        work["pending"] = pending
        _put(conn, agent_id, number, work)
        return _select(conn, agent_id, number)


def say(agent_id: str, number: int, event: dict) -> dict:
    """Log Prosper AI's `event` (a message, a proposed change) with the changes it made since it
    last spoke under it: their lines in its details, their rules and tests after it. Returns it.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        work = _work(conn, agent_id, number)
        pending = work.pop("pending", None) or {"lines": [], "events": []}
        if pending["lines"] or pending["events"]:
            details = [*event.get("details", []), *pending["lines"]]
            event = {**event, "details": details, "changed": True}
        _record_event(conn, agent_id, pull, event)
        for change in pending["events"]:
            _record_event(conn, agent_id, _select(conn, agent_id, number), change)
        _put(conn, agent_id, number, work)
        return _select(conn, agent_id, number)


def unsaid(agent_id: str, number: int) -> bool:
    """Whether Prosper AI changed the copy since it last said why."""
    pending = work_of(agent_id, number).get("pending") or {}
    return bool(pending.get("lines") or pending.get("events"))


def log(agent_id: str, number: int, event: dict) -> dict:
    """Add `event` to the pull request's conversation. Returns it."""
    with connect() as conn:
        pull = _require(conn, agent_id, number)
        _record_event(conn, agent_id, pull, event)
        return _select(conn, agent_id, number)


def ask(
    agent_id: str,
    number: int,
    questions: list[dict],
    setup: bool = False,
    kind: Optional[str] = None,
) -> dict:
    """Ask the person `questions`, each { text, options: [{ label, rule }] }. Returns the PR.

    Each is logged as one event with its options; the rule each option becomes
    stays in the store until it is picked. Prosper AI then waits. A `setup`
    question is asked before anything is drawn: its options have no rule, and
    once all of them have answers the setup goes on to draw the agent. A
    question of another `kind` asks what to do next (a fix it could not
    reproduce: go on or stop); its options have no rule either, and the job
    that asked it reads the answer.
    """
    with connect() as conn:
        _require(conn, agent_id, number)
        work = _work(conn, agent_id, number)
        for question in questions:
            asked = {"id": new_id(), **question, "answer": None, "setup": setup, "kind": kind}
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


def pick(
    agent_id: str, number: int, question: str, option: int
) -> tuple[dict, bool, Optional[str]]:
    """The person picks option `option` of `question`; an option that is a rule goes into the copy.

    Returns the pull request, whether every question has its answer now, and
    the question's kind ("setup", "go_on", or None): Prosper AI goes on once
    every one has its answer. Refused while Prosper AI works: it would write
    over the copy as the rule goes in.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by="you")
        work = _work(conn, agent_id, number)
        asked = _open_question(work, question)
        if not 0 <= option < len(asked["options"]):
            raise Conflict(f"That question has no option {option + 1}.")
        chosen = asked["options"][option]
        asked["answer"] = chosen["label"]
        done = _answered(work)
        _put(conn, agent_id, number, work)
        _record_event(
            conn, agent_id, pull, _event("answer", "you", question=question, text=chosen["label"])
        )
        if chosen.get("rule"):
            rule = {
                "id": new_id(),
                "step": chosen["rule"]["step"],
                "text": chosen["rule"]["text"],
                "source": {"kind": "answer", "pull": number, "quote": chosen["label"]},
            }
            pull = _select(conn, agent_id, number)
            added = _event("rule", PROSPER, step=rule["step"], text=rule["text"])
            rules = prune_rules([*pull["rules"], rule], pull["config"])
            _record_event(conn, agent_id, pull, added, rules=json.dumps(rules))
        return _select(conn, agent_id, number), done, _kind(asked)


def _kind(question: dict) -> Optional[str]:
    return "setup" if question.get("setup") else question.get("kind")


def _answered(work: dict) -> bool:
    """Whether every question has its answer; if so, Prosper AI goes on, else it waits."""
    done = all(q["answer"] is not None for q in work.get("questions", []))
    work.update(
        state="working" if done else "waiting", doing="Reading your answer" if done else None
    )
    return done


def take_message(agent_id: str, number: int, text: str) -> tuple[dict, Optional[dict], bool]:
    """Log the person's message to Prosper AI. Returns the pull request, the question it
    answers (while Prosper AI waits for one, the first still open), and whether Prosper AI
    goes on now: not while other questions wait for their answers. Refused while it works.
    """
    with connect() as conn:
        pull = _require(conn, agent_id, number, by="you")
        work = _work(conn, agent_id, number)
        answers = None
        if work.get("state") == "waiting" and any(
            q["answer"] is None for q in work.get("questions", [])
        ):
            answers = _open_question(work, None)
            answers["answer"] = text
            event = _event("answer", "you", question=answers["id"], text=text)
            going = _answered(work)
        else:
            event = _event("message", "you", text=text)
            work.update(state="working", doing="Reading your message")
            going = True
        _put(conn, agent_id, number, work)
        _record_event(conn, agent_id, pull, event)
        return _select(conn, agent_id, number), answers, going


def guidelines(agent_id: str) -> tuple[list[dict], list[dict]]:
    """What the agent was built from: the sources of its setup and the questions answered there.

    Every later pull request reads these, so a fix or a change is held to the
    same guidelines as the setup. Both empty for an agent drawn by hand.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT prosper FROM pulls WHERE agent_id = ? AND kind = 'setup'"
            " AND prosper IS NOT NULL ORDER BY number DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
    work = json.loads(row["prosper"]) if row else {}
    answered = [q for q in work.get("questions", []) if q["answer"]]
    return work.get("sources", []), answered


def waiting_for(agent_id: str, number: int) -> list[dict]:
    """The questions Prosper AI asked on the pull request that have no answer yet."""
    return [q for q in work_of(agent_id, number).get("questions", []) if q["answer"] is None]
