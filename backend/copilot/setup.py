#
# Prosper AI setting up a new agent from a clinic's guidelines, inside its PR #1.
#
# A background job, one request to the model per artifact, each logged in the
# pull request's conversation as it lands, so the person watches it happen:
#
#   read the files (done before the job, as the agent is created)
#   -> draw the agent       "Drew 5 steps"        the graph shows up in Build
#   -> write its rules      "Wrote 5 rules, each linked to its line"
#      write its tests      "Wrote 7 tests"
#      look for gaps        questions with options, if the guidelines leave one
#   -> run the suite        the checks' own events
#
# Rules, tests and gaps are asked for at once: each needs only the guidelines
# and the agent. The suite runs once the questions have their answers, not
# before: an answer changes the agent, and a run before it would be paid for
# and thrown away.
#
# The person can also write to Prosper AI in the pull request (`change`): the
# answer to a question in their own words, or a change ("make the greeting
# shorter"). Prosper AI rewrites PR #1's copy through the same checks, says what
# it changed, and the suite runs again.
#
# Jobs run in a small thread pool: the OpenAI SDK's sync client is enough for
# a few requests in a row, and the server's event loop (voice calls) never
# waits on them. A job that fails says so in the conversation, and the next
# message to Prosper AI tries again.
#

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from loguru import logger

import store
from store.db import now
from store.prosper import PROSPER
from store.suite import added_in

from . import artifacts
from .llm import LLM

# Who Prosper AI talks to. The tests swap it for a scripted model.
new_llm: Callable[[], LLM] = LLM

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prosper")
_jobs: list[Future] = []
_lock = threading.Lock()


def _event(kind: str, **more) -> dict:
    return {"type": kind, "by": PROSPER, "at": now(), **more}


def build(agent_id: str, number: int) -> Future:
    """Build the agent in pull request `number` from the guidelines it was opened with."""
    return _submit(_build, agent_id, number)


def change(agent_id: str, number: int, text: str, answers: Optional[dict] = None) -> Future:
    """Make the change the person asked for in `text`; with `answers`, it answers that question."""
    return _submit(_change, agent_id, number, text, answers)


def wait(timeout: float = 30) -> None:
    """Wait for the jobs in progress to finish. For tests."""
    with _lock:
        jobs = list(_jobs)
    for job in jobs:
        job.result(timeout)


def _submit(job, agent_id: str, number: int, *args) -> Future:
    future = _pool.submit(_guarded, job, agent_id, number, *args)
    with _lock:
        _jobs[:] = [j for j in _jobs if not j.done()] + [future]
    return future


def _guarded(job, agent_id: str, number: int, *args) -> None:
    llm = new_llm()
    try:
        job(llm, agent_id, number, *args)
    except Exception as error:  # noqa: BLE001 - said in the conversation, never lost in a thread
        logger.exception(f"Prosper AI could not finish on agent {agent_id}")
        reason = str(error) or type(error).__name__
        reason = reason if len(reason) <= 200 else reason[:199] + "…"
        try:
            store.prosper.log(
                agent_id,
                number,
                _event(
                    "message",
                    text=f"I couldn't finish: {reason} Write to me to try again, "
                    "or say what to change.",
                ),
            )
            store.prosper.set_state(agent_id, number, "failed")
        except store.NotFound:
            pass  # the agent was deleted meanwhile
    finally:
        logger.info(f"Prosper AI spent on agent {agent_id}: {llm.usage}")
        try:
            store.prosper.spend(agent_id, number, llm.usage)
        except store.NotFound:
            pass


def _sources(work: dict) -> str:
    names = ", ".join(f'"{source["name"]}"' for source in work["sources"])
    texts = "\n\n".join(f"=== {s['name']} ===\n{s['text']}" for s in work["sources"])
    return f"The guidelines, from {len(work['sources'])} sources: {names}.\n\n{texts}"


def _agent(config: dict) -> str:
    return "The agent:\n" + json.dumps(artifacts.from_config(config), indent=1)


def _count(n: int, one: str) -> str:
    return f"{n} {one}{'' if n == 1 else 's'}"


def _build(llm: LLM, agent_id: str, number: int) -> None:
    work = store.prosper.work_of(agent_id, number)
    name = store.get_pull(agent_id, number)["config"]["name"]
    guidelines = _sources(work)
    store.prosper.set_state(agent_id, number, "working", "Drawing the steps")

    drawn: dict = {}

    def agent_ok(answer: dict) -> None:
        drawn["config"] = artifacts.to_config(name, answer)
        artifacts.check_agent(drawn["config"])

    llm.ask("agent", f"The agent is called {name}.\n\n{guidelines}", artifacts.AGENT, agent_ok)
    config = drawn["config"]
    drew = _event("step", text=f"Drew {_count(len(config['nodes']), 'step')}")
    store.prosper.write(
        agent_id, number, drew, config=config, state="working", doing="Writing rules and tests"
    )

    about = f"{guidelines}\n\n{_agent(config)}"
    with ThreadPoolExecutor(max_workers=3) as pool:
        rules = pool.submit(
            llm.ask,
            "rules",
            about,
            artifacts.RULES,
            lambda answer: artifacts.check_rules(answer, config, work["sources"]),
        )
        tests = pool.submit(
            llm.ask,
            "tests",
            about,
            artifacts.TESTS,
            lambda answer: artifacts.check_tests(answer["tests"], config),
        )
        gaps = pool.submit(
            llm.ask,
            "questions",
            about,
            artifacts.QUESTIONS,
            lambda answer: artifacts.check_questions(answer, config),
        )
        written = artifacts.rules_from(rules.result(), number)
        said = (
            f"Wrote {_count(len(written), 'rule')}, each linked to its line"
            if written
            else "Wrote no rules: the steps already say everything the guidelines ask"
        )
        store.prosper.write(
            agent_id, number, _event("step", text=said), rules=written, doing="Writing tests"
        )
        source = {"kind": "guidelines", "pull": number}
        suite = [{**test, "source": source} for test in tests.result()["tests"]]
        store.prosper.write(
            agent_id,
            number,
            _event("step", text=f"Wrote {_count(len(suite), 'test')}"),
            tests=suite,
            doing="Looking for gaps in the guidelines",
        )
        questions = gaps.result()["questions"]
    for question in questions:
        for option in question["options"]:
            option["rule"]["step"] = artifacts.step_of(option["rule"]["step"])
    if questions:
        store.prosper.ask(agent_id, number, questions)
    else:
        _ready(agent_id, number)


def _change(llm: LLM, agent_id: str, number: int, text: str, answers: Optional[dict]) -> None:
    pull = store.get_pull(agent_id, number)
    if not pull["config"]["nodes"]:
        # The setup failed before the agent was drawn: this is the "try again".
        return _build(llm, agent_id, number)
    work = store.prosper.work_of(agent_id, number)
    # With their ids, so a change can take out one this pull request added.
    rules = "\n".join(
        f"- [{rule['id']}] {rule['step'] or 'every step'}: {rule['text']}" for rule in pull["rules"]
    )
    tests = "\n".join(
        f"- [{test['id']}] {test['name']} · caller: {test['caller']} · checks: "
        f"{'; '.join(test['checks'])}"
        for test in pull["tests"]
    )
    removable = {
        item["id"] for kind in ("rules", "tests") for item in pull[kind] if added_in(item, number)
    }
    if answers is not None:
        request = (
            f'You asked: "{answers["text"]}" Their answer: "{text}". '
            "Make the agent follow it, as a rule or as a change to its steps."
        )
    else:
        request = text
    content = (
        f"{_sources(work)}\n\n{_agent(pull['config'])}\n\nIts rules:\n{rules or '(none)'}"
        f"\n\nIts tests:\n{tests or '(none)'}\n\nThe request: {request}"
    )
    changed: dict = {}

    def change_ok(answer: dict) -> None:
        changed["config"] = artifacts.check_change(
            answer, pull["config"]["name"], pull["config"], removable
        )

    answer = llm.ask("change", content, artifacts.CHANGE, change_ok)
    config = changed["config"]
    moved = config != pull["config"]
    source = {"kind": "answer" if answers else "request", "pull": number, "quote": text}
    store.prosper.write(
        agent_id,
        number,
        _event("message", text=answer["reply"], **({"changed": True} if moved else {})),
        config=config if moved else None,
    )
    for item in answer["remove"]:
        kind = "rules" if any(rule["id"] == item for rule in pull["rules"]) else "tests"
        store.take_out(agent_id, number, kind, item, PROSPER)
    for rule in answer["rules"]:
        step = artifacts.step_of(rule["step"])
        store.prosper.write(
            agent_id,
            number,
            _event("rule", step=step, text=rule["text"]),
            rules=({"step": step, "text": rule["text"], "source": source},),
        )
    for test in answer["tests"]:
        store.prosper.write(
            agent_id,
            number,
            _event("test", text=test["name"]),
            tests=({**test, "source": source},),
        )
    if store.prosper.waiting_for(agent_id, number):
        store.prosper.set_state(agent_id, number, "waiting")
    else:
        _ready(agent_id, number)


def _ready(agent_id: str, number: int) -> None:
    """Prosper AI is done: the suite runs on the copy as it is now."""
    from api import checks  # the API runs the checks; imported late, it also mounts this

    store.prosper.set_state(agent_id, number, "done")
    checks.start(agent_id, pull=number)

