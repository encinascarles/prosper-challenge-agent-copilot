#
# Prosper AI fixing an issue found in calls, inside the pull request "Fix with
# Prosper AI" opened for it, the way a coding agent fixes a bug:
#
#   reproduce   one test written from the issue's calls (who called, what they
#               said, the turn where it went wrong), run on the version the
#               calls had, 3 times. It must fail (below 2 of 3) to count. If it
#               passes, one more try with a sharper caller; if that passes too,
#               Prosper AI says so and asks whether to go on anyway.
#   propose     the smallest change that makes the agent do what the test asks
#               (a rule on the right step, a step's text, a field, an edge),
#               checked like any change Prosper AI makes, and held to two steps
#   prove       the whole suite plus the new test, on the pull request's copy;
#               failing tests go to the same self-check as a setup's (setup.py),
#               and once they pass Prosper AI says it with the new test's score
#               before and after ("0/3 on v1 → 3/3")
#
# The test stays in the suite once merged: the issue cannot come back without a
# test saying so. Each step is logged in the conversation as it lands, and
# remembered, so a retry after a failure starts from the step that failed.
#
# It runs as one of Prosper AI's jobs (setup.py has the pool, the busy guard and
# the retry). The reproduction's calls are paid like any test's and counted
# with what Prosper AI spent on the pull request.
#

import asyncio
from typing import Optional

import simulate
import store
from simulate.suite import prosper_model
from store.runs import verdict
from store.suite import new_id

from . import artifacts
from .calls import _context
from .llm import LLM, price
from .setup import _agent, _answered, _event, _ready, _sources, _the_call

TRIES = 2  # tests written to reproduce an issue before asking whether to go on
CALLS_SHOWN = 3  # of the issue's calls, the latest, given to write the test
LINES_BEFORE = 10  # of each call, the lines before the bad turn


def run(llm: LLM, agent_id: str, number: int, job: dict) -> None:
    """Fix the issue the pull request is for, from the step its work stopped at."""
    pull = store.get_pull(agent_id, number)
    issue = store.issues.get_issue(agent_id, pull["fixes"])
    version = store.get_version(agent_id, pull["base_version"])
    work = store.prosper.work_of(agent_id, number)
    built = set(work.get("built", []))
    hint = job.get("hint") or job.get("said")
    if job["kind"] == "go_on":
        if not job["go"]:
            text = (
                f"Left it as it is: {_v(version)} stays unchanged. Close this pull request, "
                "or tell me what to change."
            )
            store.prosper.write(agent_id, number, _event("message", text=text), state="done")
            return
        if "reproduced" not in built:
            _keep_anyway(agent_id, number, version, work["candidate"])
            built.add("reproduced")
    if "reproduced" not in built and not _reproduce(llm, agent_id, number, issue, version):
        return  # it asked whether to go on
    if "proposed" not in built:
        _propose(llm, agent_id, number, issue, version, hint)
    _ready(agent_id, number)


def _v(version: dict) -> str:
    return f"v{version['number']}"


def _issue(issue: dict) -> str:
    return (
        f"The issue, Issue #{issue['number']} ({issue['severity']}), first seen in step "
        f"{issue['step']}: {issue['title']}. {issue['description']}"
    )


def _calls(agent_id: str, issue: dict) -> str:
    """The issue's latest calls as a test writer reads them: who called, and up to the bad turn."""
    shown = []
    for found in issue["findings"][:CALLS_SHOWN]:
        call = store.calls.get_call(agent_id, found["call"])
        if call is None:
            continue
        start = max(0, found["turn"] - LINES_BEFORE)
        lines = "\n".join(
            f"  [{i}] {line['role']}: {line['text']}"
            for i, line in enumerate(call["transcript"][start : found["turn"] + 1], start)
        )
        shown.append(
            f"- {call['caller']}, on v{call['version']}. Who they were: {call['situation']}\n"
            f'  It went wrong on turn {found["turn"]} ("{found["quote"]}"): {found["why"]}\n'
            f"{lines}"
        )
    return f"Its calls ({issue['calls']} in all, the latest {len(shown)} here):\n" + "\n\n".join(
        shown
    )


def _callers(issue: dict) -> str:
    names = list(dict.fromkeys(found["caller"] for found in issue["findings"]))
    if len(names) == 1:
        return f"calls like {names[0]}"
    return f"calls like these {len(names)} callers"


def _play(llm: LLM, version: dict, test: dict) -> list[dict]:
    """The test called REPEATS times on `version`, each call checked. Its cost goes to `llm`."""
    from api import checks  # who the calls talk to: the tests swap them for fakes

    results: list[dict] = []
    services = checks.services or simulate.Services()

    async def play() -> None:
        try:
            await simulate.run_suite(
                version["config"],
                version["rules"],
                [{"id": "reproduce", **test}],
                lambda _, result: results.append(result),
                services=services,
            )
        finally:
            if services is not checks.services:
                # Its client belongs to this loop: closed with it, not after.
                await services.close()

    asyncio.run(play())
    model = version["config"].get("model", "")
    usd = 0.0
    for result in results:
        tokens = result["tokens"]
        usd += price(model, **tokens.get("agent", {}))
        for part in ("caller", "judge"):
            said = tokens.get(part, {})
            usd += price(prosper_model(), said.get("prompt", 0), said.get("completion", 0))
    llm.add_cost(usd)
    return results


def _passed(results: list[dict]) -> int:
    return sum(1 for result in results if result["passed"])


def _how_it_went(results: list[dict]) -> list[str]:
    """One line per call of a test: passed, or the checks it failed and why."""
    lines = []
    for i, result in enumerate(results, 1):
        failed = [c for c in result["checks"] if not c["pass"]]
        if not failed:
            lines.append(f"Call {i} passed")
            continue
        why = "; ".join(f"{c['text']}: {c['detail']}" for c in failed)
        lines.append(f"Call {i} failed · {why}")
    return lines


def _reproduce(llm: LLM, agent_id: str, number: int, issue: dict, version: dict) -> bool:
    """Write and run a test that fails like the issue's calls. Returns whether it did.

    If none does after TRIES, it says so and asks whether to go on.
    """
    store.prosper.set_state(agent_id, number, "working", f"Reproducing it on {_v(version)}")
    tests = "\n".join(
        f"- {test['name']} · caller: {test['caller']} · checks: {'; '.join(test['checks'])}"
        for test in version["tests"]
    )
    content = (
        f"{_context(agent_id, version)}\n\nIts tests:\n{tests or '(none)'}\n\n"
        f"{_issue(issue)}\n\n{_calls(agent_id, issue)}"
    )
    results: list[dict] = []
    for attempt in range(TRIES):
        test = llm.ask(
            "reproduce",
            content,
            artifacts.REPRODUCE,
            lambda a: artifacts.check_reproduction(a, version["config"]),
        )
        results = _play(llm, version, test)
        passed = _passed(results)
        if verdict({"runs": results}, simulate.REPEATS) == "failing":
            _keep(agent_id, number, issue, version, test, results)
            return True
        store.prosper.update(agent_id, number, candidate={"test": test, "passed": passed})
        if attempt + 1 < TRIES:
            score = f"{passed}/{len(results)} on {_v(version)}"
            said = f"A first test passed {score}: trying a sharper caller"
            store.prosper.log(agent_id, number, _event("step", text=said))
            content += (
                f'\n\nYour test "{test["name"]}" passed {passed} of {len(results)} calls on '
                f"{_v(version)}, so it did not reproduce the problem.\n"
                f"Its caller: {test['caller']}\n"
                f"How one of its calls went:\n{_the_call(results[0])}\n\n"
                "Write a sharper caller: one who does what the issue's callers did, at the "
                "moment they did it, and checks that catch exactly what went wrong."
            )
    passed = _passed(results)
    text = (
        f"Could not reproduce it on {_v(version)}: {passed}/{len(results)}. "
        "It may be rare or already fixed."
    )
    store.prosper.log(agent_id, number, _event("message", text=text, details=_how_it_went(results)))
    question = {
        "text": "Propose a fix anyway, with the test I wrote?",
        "options": [
            {"label": "Yes, propose a fix anyway", "rule": None},
            {"label": "No, leave it as it is", "rule": None},
        ],
    }
    store.prosper.ask(agent_id, number, [question], kind="go_on")
    return False


def _source(number: int, issue: int, version: dict, passed: int, runs: int) -> dict:
    before = {"version": version["number"], "passed": passed, "runs": runs}
    return {"kind": "issue", "pull": number, "issue": issue, "before": before}


def _keep(agent_id: str, number: int, issue: dict, version: dict, test: dict, results: list):
    """The test reproduced the issue: it joins the pull request's copy, said as a card."""
    passed, runs = _passed(results), len(results)
    kept = {
        "id": new_id(),
        **test,
        "source": _source(number, issue["number"], version, passed, runs),
    }
    event = _event(
        "reproduced",
        text=f"Reproduced it: a test that {_callers(issue)} fails on {_v(version)} · "
        f"{passed}/{runs}",
        test=kept["id"],
        version=version["number"],
        passed=passed,
        total=runs,
        details=_how_it_went(results),
    )
    store.prosper.write(agent_id, number, event, tests=(kept,), built="reproduced")
    store.prosper.update(agent_id, number, failed_on=[r for r in results if not r["passed"]][:1])


def _keep_anyway(agent_id: str, number: int, version: dict, candidate: dict) -> None:
    """The person chose to go on: the test that did not reproduce it joins the copy anyway."""
    pull = store.get_pull(agent_id, number)
    test, passed = candidate["test"], candidate["passed"]
    source = _source(number, pull["fixes"], version, passed, simulate.REPEATS)
    kept = {"id": new_id(), **test, "source": source}
    said = f"Added the test anyway: {passed}/{simulate.REPEATS} on {_v(version)}"
    store.prosper.write(
        agent_id, number, _event("step", text=said), tests=(kept,), built="reproduced"
    )


def _words(name: str) -> str:
    # As the editor shows a step's name: "offer_times" is "Offer times".
    return name.replace("_", " ").capitalize()


def _what(before: dict, after: dict) -> list[str]:
    words = {
        "added": "Added step {}",
        "removed": "Took out step {}",
        "task": "Changed what {} says",
        "edges": "Changed when {} moves on",
    }
    lines = [
        words[kind].format(_words(name)) for name, kind in artifacts.changed_steps(before, after)
    ]
    if after.get("persona") != before.get("persona"):
        lines.append("Changed the persona")
    return lines


def _propose(
    llm: LLM, agent_id: str, number: int, issue: dict, version: dict, hint: Optional[str]
) -> None:
    """Ask for the smallest change that fixes the issue, and write it to the copy."""
    store.prosper.set_state(agent_id, number, "working", "Proposing the smallest change")
    pull = store.get_pull(agent_id, number)
    work = store.prosper.work_of(agent_id, number)
    test = next((t for t in pull["tests"] if t["source"]["kind"] == "issue"), None)
    rules = "\n".join(f"- {r['step'] or 'every step'}: {r['text']}" for r in pull["rules"])
    failing = ""
    if test is not None:
        before = test["source"]["before"]
        failing = (
            f"\n\nThe test that reproduces it, which the fix must make pass: {test['name']}\n"
            f"  caller: {test['caller']}\n  checks: {'; '.join(test['checks'])}\n"
            f"  on {_v(version)}: passed {before['passed']} of {before['runs']} calls"
        )
        for result in work.get("failed_on", []):
            failing += f"\nOne of its calls on {_v(version)}:\n{_the_call(result)}"
    said = f'\n\nThe person said: "{hint}"' if hint else ""
    content = (
        f"{_sources(work, agent_id)}\n\nThe clinic's answers:\n{_answered(agent_id, work)}\n\n"
        f"{_agent(pull['config'])}\n\nIts rules:\n{rules or '(none)'}\n\n{_issue(issue)}"
        f"{failing}{said}"
    )
    fixed: dict = {}

    def fix_ok(answer: dict) -> None:
        fixed["config"] = artifacts.check_fix(answer, pull["config"])

    answer = llm.ask("fix", content, artifacts.FIX, fix_ok)
    config = fixed["config"]
    moved = config != pull["config"]
    event = _event(
        "proposed", text=answer["reply"], details=_what(pull["config"], config), changed=True
    )
    store.prosper.write(agent_id, number, event, config=config if moved else None)
    source = {"kind": "issue", "pull": number, "issue": issue["number"]}
    for rule in answer["rules"]:
        step = artifacts.step_of(rule["step"])
        store.prosper.write(
            agent_id,
            number,
            _event("rule", step=step, text=rule["text"]),
            rules=({"step": step, "text": rule["text"], "source": source},),
        )
    store.prosper.mark_built(agent_id, number, "proposed")


def proved(agent_id: str, number: int) -> None:
    """The fix's checks passed: say so, with the new test before and after. Once per run."""
    pull = store.get_pull(agent_id, number)
    last = next((e for e in reversed(pull["events"]) if e["type"] != "checks"), None)
    if last is not None and last["type"] == "proved":
        return
    checks = pull["checks"]
    run = store.get_run(agent_id, pull=number) or {"tests": []}
    head = (
        f"Checks pass · {checks['passed'] + checks['flaky']}/{checks['total']}, "
        f"{checks['flaky']} flaky"
        if checks["flaky"]
        else f"All checks passed · {checks['total']}/{checks['total']}"
    )
    text = f"{head} · {simulate.REPEATS} runs each"
    test = next((t for t in pull["tests"] if t["source"]["kind"] == "issue"), None)
    result = next((r for r in run["tests"] if test and r["id"] == test["id"]), None)
    more = {}
    if test is not None and result is not None:
        before = test["source"]["before"]
        after = _passed(result["runs"])
        text += (
            f" · the new test {before['passed']}/{before['runs']} on v{before['version']}"
            f" → {after}/{len(result['runs'])}"
        )
        more = {"test": test["id"]}
    counts = {key: checks[key] for key in ("passed", "flaky", "total")}
    store.prosper.log(agent_id, number, _event("proved", text=text, **counts, **more))
