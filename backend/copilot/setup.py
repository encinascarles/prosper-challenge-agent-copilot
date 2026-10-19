#
# Prosper AI setting up a new agent from a clinic's guidelines, inside its PR #1.
#
# A background job, one request to the model per artifact, each logged in the
# pull request's conversation as it lands, so the person watches it happen:
#
#   read the files (done before the job, as the agent is created)
#   -> look for gaps        questions with options, before anything is drawn;
#                           Prosper AI waits for every answer
#   -> draw the agent       "Drew 5 steps", with the answers: the graph shows up
#   -> write its rules      each linked to its line, or to the answer it is
#   -> write its tests      from the guidelines and the answers
#   -> run the suite        the checks' own events
#   -> check its own draft  for each failing test: is the agent wrong (fix it),
#                           does the test ask for more than the guidelines say
#                           (rewrite it, saying why), or is it a gap (ask)
#                           at most MAX_ROUNDS times, then it says what still fails
#
# Questions come first because an answer changes what gets drawn and what gets
# tested: asked after, an answer turned into a rule could contradict tests
# already written (a date of birth the test callers never give) and steps
# drawn without it. Tests come last, so they test the agent the clinic
# described, answers included.
#
# The person can also write to Prosper AI in the pull request (`change`): the
# answer to a question in their own words, or a change ("make the greeting
# shorter"). Prosper AI rewrites PR #1's copy through the same checks, says what
# it changed, and the suite runs again.
#
# Jobs run in a small thread pool: the OpenAI SDK's sync client is enough for
# a few requests in a row, and the server's event loop (voice calls) never
# waits on them. A job that fails (or is cut by a restart) says so in the
# conversation and stays remembered: the next message to Prosper AI retries
# it, the setup from the step it stopped at, a change with the answer it was
# for.
#

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from loguru import logger

import store
from store.db import now
from store.prosper import PROSPER
from store.runs import verdict
from store.suite import added_in

from . import artifacts
from .llm import LLM

# Who Prosper AI talks to. The tests swap it for a scripted model.
new_llm: Callable[[], LLM] = LLM

# Times Prosper AI checks its own work after a run, before it hands over.
MAX_ROUNDS = 2
VERDICT_WORDS = {
    "agent": "the agent was wrong",
    "test": "the test asked for more than the guidelines say",
    "gap": "the guidelines leave this open",
}

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="prosper")
_jobs: list[Future] = []
_lock = threading.Lock()


def _event(kind: str, **more) -> dict:
    return {"type": kind, "by": PROSPER, "at": now(), **more}


def build(agent_id: str, number: int) -> Future:
    """Build the agent in pull request `number` from the guidelines it was opened with."""
    return _submit({"kind": "build"}, agent_id, number)


def change(agent_id: str, number: int, text: str, answers: Optional[dict] = None) -> Future:
    """Make the change the person asked for in `text`; with `answers`, it answers that question."""
    job = {"kind": "change", "text": text, "question": answers["id"] if answers else None}
    return _submit(job, agent_id, number)


def fix(agent_id: str, number: int) -> Future:
    """Fix the issue pull request `number` was opened for (fix.py)."""
    return _submit({"kind": "fix"}, agent_id, number)


def go_on(agent_id: str, number: int, go: bool, hint: Optional[str] = None) -> Future:
    """Go on with a fix that could not reproduce its issue, or stop, as the person answered."""
    return _submit({"kind": "go_on", "go": go, "hint": hint}, agent_id, number)


def retry(agent_id: str, number: int, job: dict, said: str) -> Future:
    """Run again the job that failed; `said` is what the person wrote to ask for it."""
    return _submit({**job, "said": said}, agent_id, number)


def wait(timeout: float = 30) -> None:
    """Wait for the jobs in progress to finish. For tests."""
    with _lock:
        jobs = list(_jobs)
    for job in jobs:
        job.result(timeout)


def _submit(job: dict, agent_id: str, number: int) -> Future:
    future = _pool.submit(_guarded, job, agent_id, number)
    with _lock:
        _jobs[:] = [j for j in _jobs if not j.done()] + [future]
    return future


def _guarded(job: dict, agent_id: str, number: int) -> None:
    llm = new_llm()
    try:
        store.prosper.set_job(agent_id, number, {k: v for k, v in job.items() if k != "said"})
        _run(llm, agent_id, number, job)
        store.prosper.set_job(agent_id, number, None)
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


def after_checks(agent_id: str, number: int) -> None:
    """A run of the pull request's checks finished: Prosper AI checks its own work if it failed.

    Only after a change of Prosper AI's own (its setup, an answer it turned
    into a rule, its last fix), not after the person's edits, and at most
    MAX_ROUNDS times; then it says what still fails and leaves it to them.
    On a fix whose checks pass, it says so, with the test that reproduced
    the issue before and after.
    """
    pull = store.get_pull(agent_id, number)
    if pull is None or pull["state"] != "open" or pull["prosper"] is None:
        return
    work = store.prosper.work_of(agent_id, number)
    checks = pull["checks"]
    if work.get("state") != "done" or not checks:
        return
    last = next((e for e in reversed(pull["events"]) if e["type"] != "checks"), None)
    if last is None or last["by"] != PROSPER:
        return
    if checks["state"] == "passed" and pull["fixes"]:
        from . import fix

        return fix.proved(agent_id, number)
    if checks["state"] != "failed":
        return
    rounds = work.get("rounds", 0)
    if rounds >= MAX_ROUNDS:
        if not work.get("handed_over"):
            failing = ", ".join(_failing_tests(agent_id, number).values())
            text = (
                f"Still failing after {MAX_ROUNDS} rounds of checking my own work: {failing}. "
                "Tell me what to change, or change it in Build."
            )
            store.prosper.log(agent_id, number, _event("message", text=text))
            store.prosper.update(agent_id, number, handed_over=True)
        return
    store.prosper.update(agent_id, number, rounds=rounds + 1)
    store.prosper.set_state(agent_id, number, "working", "Checking why tests fail")
    _submit({"kind": "review"}, agent_id, number)


def _run(llm: LLM, agent_id: str, number: int, job: dict) -> None:
    if job["kind"] == "review":
        return _review(llm, agent_id, number)
    if job["kind"] in ("fix", "go_on"):
        from . import fix  # it builds on this module's helpers

        return fix.run(llm, agent_id, number, job)
    # A change asked for before the agent was ever drawn is a setup to finish first.
    if job["kind"] == "build" or not store.get_pull(agent_id, number)["config"]["nodes"]:
        return _build(llm, agent_id, number)
    answers = None
    if job.get("question"):
        asked = store.prosper.work_of(agent_id, number).get("questions", [])
        answers = next((q for q in asked if q["id"] == job["question"]), None)
    said = job.get("said")
    extra = said if said and said.strip() != job["text"].strip() else None
    return _change(llm, agent_id, number, job["text"], answers, extra)


def _sources(work: dict, agent_id: Optional[str] = None) -> str:
    """The guidelines as a request reads them: the setup's own, or (`agent_id`) the agent's."""
    sources = work.get("sources") or (store.prosper.guidelines(agent_id)[0] if agent_id else [])
    if not sources:
        return "No written guidelines: the agent's steps and rules are what the clinic asked."
    names = ", ".join(f'"{source["name"]}"' for source in sources)
    texts = "\n\n".join(f"=== {s['name']} ===\n{s['text']}" for s in sources)
    return f"The guidelines, from {len(sources)} sources: {names}.\n\n{texts}"


def _answered(agent_id: str, work: dict) -> str:
    """The clinic's answers to Prosper AI's questions: in this pull request, and in the setup."""
    asked = [q for q in work.get("questions", []) if q["answer"]]
    if not work.get("sources"):
        asked = store.prosper.guidelines(agent_id)[1] + asked
    return "\n".join(f'- "{q["text"]}" → "{q["answer"]}"' for q in asked) or "(none)"


def _fixes(agent_id: str, pull: dict) -> str:
    """What a fix is for, for any request on it: the issue, as it was found in calls."""
    if not pull.get("fixes"):
        return ""
    issue = store.issues.get_issue(agent_id, pull["fixes"])
    if issue is None:
        return ""
    return (
        f"\n\nThis pull request fixes Issue #{issue['number']}, found in {issue['calls']} calls: "
        f"{issue['title']}. {issue['description']}"
    )


def _agent(config: dict) -> str:
    return "The agent:\n" + json.dumps(artifacts.from_config(config), indent=1)


def _count(n: int, one: str) -> str:
    return f"{n} {one}{'' if n == 1 else 's'}"


def _build(llm: LLM, agent_id: str, number: int) -> None:
    # Resumable: a retry after a failure skips the steps already done.
    work = store.prosper.work_of(agent_id, number)
    built = set(work.get("built", []))
    config = store.get_pull(agent_id, number)["config"]
    name = config["name"]
    guidelines = _sources(work)

    if "questions" not in built:
        store.prosper.set_state(agent_id, number, "working", "Reading your guidelines")
        asked = llm.ask(
            "questions",
            f"The agent will be called {name}.\n\n{guidelines}",
            artifacts.FIRST_QUESTIONS,
            artifacts.check_first_questions,
        )
        questions = [
            {"text": q["text"], "options": [{"label": o, "rule": None} for o in q["options"]]}
            for q in asked["questions"]
        ]
        store.prosper.mark_built(agent_id, number, "questions")
        if questions:
            text = f"I need your answers before I draw {name}."
            store.prosper.log(agent_id, number, _event("message", text=text))
            store.prosper.ask(agent_id, number, questions, setup=True)
            return
        said = f"Found no gaps in the guidelines that change how {name} behaves"
        store.prosper.log(agent_id, number, _event("step", text=said))
    work = store.prosper.work_of(agent_id, number)
    setup_questions = [q for q in work.get("questions", []) if q.get("setup")]
    if any(q["answer"] is None for q in setup_questions):
        store.prosper.set_state(agent_id, number, "waiting")
        return
    answers = tuple(q["answer"] for q in setup_questions)
    given = "\n".join(f'- "{q["text"]}" → "{q["answer"]}"' for q in setup_questions)
    known = f"{guidelines}\n\nThe clinic's answers to your questions:\n{given or '(none asked)'}"

    if "agent" not in built:
        store.prosper.set_state(agent_id, number, "working", "Drawing the steps")
        drawn: dict = {}

        def agent_ok(answer: dict) -> None:
            drawn["config"] = artifacts.to_config(name, answer)
            artifacts.check_agent(drawn["config"])
            artifacts.check_concise(drawn["config"])

        llm.ask("agent", f"The agent is called {name}.\n\n{known}", artifacts.AGENT, agent_ok)
        config = drawn["config"]
        drew = _event("step", text=f"Drew {_count(len(config['nodes']), 'step')}")
        store.prosper.write(agent_id, number, drew, config=config, built="agent")

    about = f"{known}\n\n{_agent(config)}"
    if "rules" not in built:
        store.prosper.set_state(agent_id, number, "working", "Writing the rules")
        rules = llm.ask(
            "rules",
            about,
            artifacts.RULES,
            lambda a: artifacts.check_rules(a, config, work["sources"], answers),
        )
        written = artifacts.rules_from(rules, number)
        said = (
            f"Wrote {_count(len(written), 'rule')}, each linked to its line or your answer"
            if written
            else "Wrote no rules: the steps already say everything the guidelines ask"
        )
        store.prosper.write(
            agent_id, number, _event("step", text=said), rules=written, built="rules"
        )

    if "tests" not in built:
        store.prosper.set_state(agent_id, number, "working", "Writing the tests")
        pull = store.get_pull(agent_id, number)
        listed = "\n".join(f"- {r['step'] or 'every step'}: {r['text']}" for r in pull["rules"])
        tests = llm.ask(
            "tests",
            f"{about}\n\nIts rules:\n{listed or '(none)'}",
            artifacts.TESTS,
            lambda a: artifacts.check_tests(a["tests"], config, artifacts.SETUP_TESTS),
        )
        source = {"kind": "guidelines", "pull": number}
        suite = [{**test, "source": source} for test in tests["tests"]]
        done = _event("step", text=f"Wrote {_count(len(suite), 'test')}")
        store.prosper.write(agent_id, number, done, tests=suite, built="tests")

    if store.prosper.waiting_for(agent_id, number):
        store.prosper.set_state(agent_id, number, "waiting")
    else:
        _ready(agent_id, number)


def _change(
    llm: LLM,
    agent_id: str,
    number: int,
    text: str,
    answers: Optional[dict],
    extra: Optional[str] = None,
) -> None:
    pull = store.get_pull(agent_id, number)
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
    if extra:
        request += f'\nThey then wrote: "{extra}"'
    content = (
        f"{_sources(work, agent_id)}\n\nThe clinic's answers:\n{_answered(agent_id, work)}"
        f"\n\n{_agent(pull['config'])}\n\nIts rules:\n{rules or '(none)'}"
        f"\n\nIts tests:\n{tests or '(none)'}{_failing(agent_id, number)}"
        f"{_fixes(agent_id, pull)}\n\nThe request: {request}"
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


def _failing_tests(agent_id: str, number: int) -> dict:
    """The tests that failed in the latest run, by id: their names. Flaky ones are not here."""
    run = store.get_run(agent_id, pull=number) or {"tests": [], "repeats": 0}
    return {
        test["id"]: test["name"]
        for test in run["tests"]
        if verdict(test, run["repeats"]) == "failing"
    }


def _the_call(result: dict) -> str:
    """A failing run of a test as the review reads it: what failed, the path, the last lines."""
    failed = "; ".join(f"{c['text']} ({c['detail']})" for c in result["checks"] if not c["pass"])
    path = " > ".join(step["node"] for step in result["path"]) or "nowhere"
    lines = "\n".join(f"  {line['role']}: {line['text']}" for line in result["transcript"][-14:])
    return f"  failed: {failed}\n  path: {path} · ended: {result['ended']}\n{lines}"


def _review(llm: LLM, agent_id: str, number: int) -> None:
    pull = store.get_pull(agent_id, number)
    work = store.prosper.work_of(agent_id, number)
    run = store.get_run(agent_id, pull=number) or {"tests": []}
    tests = {test["id"]: test for test in pull["tests"]}
    failing = _failing_tests(agent_id, number)
    calls = []
    for result in run["tests"]:
        if result["id"] not in failing:
            continue
        bad = [r for r in result["runs"] if not r["passed"]]
        test = tests.get(result["id"], {})
        calls.append(
            f"[{result['id']}] {result['name']} · failed {len(bad)} of {len(result['runs'])}\n"
            f"  caller: {test.get('caller', '')}\n  checks: {'; '.join(test.get('checks', []))}\n"
            f"{_the_call(bad[0])}"
        )
    rules = "\n".join(
        f"- [{rule['id']}] {rule['step'] or 'every step'}: {rule['text']}" for rule in pull["rules"]
    )
    content = (
        f"{_sources(work, agent_id)}\n\nThe clinic's answers:\n{_answered(agent_id, work)}\n\n"
        f"{_agent(pull['config'])}\n\nIts rules:\n{rules or '(none)'}{_fixes(agent_id, pull)}"
        "\n\nThe failing tests:\n" + "\n\n".join(calls)
    )
    removable = {rule["id"] for rule in pull["rules"] if added_in(rule, number)}
    # The test that reproduces the issue a fix is for says what the agent must do.
    kept = {test["id"] for test in pull["tests"] if test["source"]["kind"] == "issue"}
    reviewed: dict = {}

    def review_ok(answer: dict) -> None:
        reviewed["config"] = artifacts.check_review(
            answer, failing, pull["config"], removable, kept
        )

    answer = llm.ask("review", content, artifacts.REVIEW, review_ok)
    config = reviewed["config"]
    moved = config != pull["config"]
    details = [
        f"{failing[v['test']]} · {VERDICT_WORDS[v['verdict']]}: {v['why']}"
        for v in answer["verdicts"]
    ]
    said = _event(
        "message", text=answer["summary"], details=details, **({"changed": True} if moved else {})
    )
    store.prosper.write(agent_id, number, said, config=config if moved else None)
    for rule_id in answer["remove_rules"]:
        store.take_out(agent_id, number, "rules", rule_id, PROSPER)
    source = {"kind": "check", "pull": number}
    for rule in answer["rules"]:
        step = artifacts.step_of(rule["step"])
        store.prosper.write(
            agent_id,
            number,
            _event("rule", step=step, text=rule["text"]),
            rules=({"step": step, "text": rule["text"], "source": source},),
        )
    why = {v["test"]: v["why"] for v in answer["verdicts"]}
    for test in answer["tests"]:
        fields = {key: test[key] for key in ("name", "caller", "checks")}
        store.prosper.rewrite_test(agent_id, number, test["id"], fields, why[test["id"]])
    questions = answer["questions"]
    for question in questions:
        for option in question["options"]:
            option["rule"]["step"] = artifacts.step_of(option["rule"]["step"])
    if questions:
        store.prosper.ask(agent_id, number, questions)
    else:
        _ready(agent_id, number)


def _failing(agent_id: str, number: int) -> str:
    """The checks that failed in the latest run of the copy, with why: what a fix has to change."""
    run = store.get_run(agent_id, pull=number)
    lines = []
    for test in (run or {}).get("tests", []):
        failed = [r for r in test["runs"] if not r["passed"]]
        if not failed:
            continue
        reasons = {c["text"]: c["detail"] for r in failed for c in r["checks"] if not c["pass"]}
        why = "; ".join(f"{text} ({detail})" for text, detail in list(reasons.items())[:3])
        lines.append(f"- {test['name']}: failed {len(failed)} of {len(test['runs'])} · {why}")
    return "\n\nWhat failed when its tests last ran:\n" + "\n".join(lines) if lines else ""


def _ready(agent_id: str, number: int) -> None:
    """Prosper AI is done: the suite runs on the copy as it is now."""
    from api import checks  # the API runs the checks; imported late, it also mounts this

    store.prosper.set_state(agent_id, number, "done")
    checks.start(agent_id, pull=number)
