#
# Prosper AI's work on a pull request: what its tools there stand on.
#
# Where the work stands, and the guards that read it. They are code, not the
# prompt, so no wording of a brief can talk the agent past them:
#
#   a setup     asks the clinic what its guidelines leave open before it draws
#               anything, and draws nothing until every question has its answer;
#               it never takes a test out; it runs its tests only once there are
#               5 to 7 and every answer is a rule quoting it
#   a fix       changes nothing in the copy before a test of the issue has failed
#               on the version the calls had (or the person said to go on without
#               one), never rewrites or takes out that test once it has, and
#               touches two steps at most
#   any turn    runs the whole suite three times at most: its first run and two
#               rounds of checking its own work
#
# The test that reproduces an issue is played on the base version, 3 times; it
# must fail (below 2 of 3) to count. One that passes gets one sharper try; if
# that passes too, Prosper AI asks whether to go on (a question asked here, in
# code, so the go-on is always the person's), and the merge warns of it.
#
# The copy's tests run on the checks' own loop (api/checks.py), as when a
# person runs them; a tool waits for them and reads how they went.
#

import asyncio
from typing import Optional

import simulate
import store
from simulate.suite import prosper_model
from store.db import now
from store.prosper import PROSPER
from store.runs import verdict
from store.suite import added_in, new_id

from . import artifacts, facts
from .agent import ToolError, Work
from .llm import price

TRIES = 2  # tests written to reproduce an issue before asking whether to go on
MAX_ROUNDS = 2  # whole runs after the first in one turn: checking its own work
CHECKS_WAIT = 20 * 60  # seconds a tool waits for the copy's tests


def event(kind: str, **more) -> dict:
    return {"type": kind, "by": PROSPER, "at": now(), **more}


def pull_of(work: Work) -> dict:
    return store.get_pull(work.agent_id, work.number)


def building(agent_id: str, pull: dict) -> bool:
    """A setup whose copy never ran its tests: each piece is said as it lands, as a step."""
    return pull["kind"] == "setup" and store.get_run(agent_id, pull=pull["number"]) is None


def base_of(agent_id: str, pull: dict) -> Optional[dict]:
    return store.get_version(agent_id, pull["base_version"]) if pull["base_version"] else None


class Subject:
    """What a fix or a change is for: an issue found in calls (or reported), or a request."""

    def __init__(self, agent_id: str, pull: dict):
        self.number = pull["number"]
        self.issue = store.issues.get_issue(agent_id, pull["fixes"]) if pull["fixes"] else None
        work = store.prosper.work_of(agent_id, pull["number"])
        self.request = work.get("request") or {"text": pull["title"], "what": ""}

    @property
    def tries(self) -> int:
        # A request has no calls to sharpen a caller from.
        return TRIES if self.issue else 1

    def source(self, **more) -> dict:
        """The source of a test or a rule it adds."""
        if self.issue:
            return {"kind": "issue", "pull": self.number, "issue": self.issue["number"], **more}
        return {"kind": "request", "pull": self.number, "quote": self.request["text"], **more}

    def failing(self, version: dict, passed: int, runs: int) -> str:
        if self.issue:
            return (
                f"Reproduced it: a test that {facts.callers(self.issue)} fails on "
                f"v{version['number']} · {passed}/{runs}"
            )
        return f"Wrote a test of it: it fails on v{version['number']} as it is · {passed}/{runs}"

    def passing(self, version: dict, passed: int, runs: int) -> str:
        if self.issue:
            return (
                f"Could not reproduce it on v{version['number']}: {passed}/{runs}. "
                "It may be rare or already fixed."
            )
        return (
            f"The test of it already passes on v{version['number']}: {passed}/{runs}. "
            "The agent may do this already."
        )

    def what(self) -> str:
        return "a fix" if self.issue else "the change"


def subject_of(agent_id: str, pull: dict) -> Optional[Subject]:
    return Subject(agent_id, pull) if pull["kind"] in ("fix", "change") else None


def is_test_of(test: dict, number: int) -> bool:
    """Whether `test` is the one pull request `number` wrote first, to reproduce what it is for."""
    return bool(test["source"].get("before")) and test["source"].get("pull") == number


def source_of(agent_id: str, pull: dict, **more) -> dict:
    """The source of what Prosper AI adds without quoting: the issue, the request, or the
    person's message in their own pull request."""
    if subject := subject_of(agent_id, pull):
        return subject.source(**more)
    kind = "guidelines" if pull["kind"] == "setup" else "request"
    return {"kind": kind, "pull": pull["number"], **more}


# ---- guards ---------------------------------------------------------------


def may_edit(work: Work, pull: dict) -> None:
    """Raise ToolError while the work is not at a point where the copy may change."""
    done = set(store.prosper.work_of(work.agent_id, work.number).get("built", []))
    if pull["kind"] == "setup":
        if "asked" not in done:
            raise ToolError(
                "Ask the clinic what the guidelines leave open first (ask), before anything "
                "is drawn; with nothing open, call ask with no questions."
            )
        if store.prosper.waiting_for(work.agent_id, work.number):
            raise ToolError("The clinic has not answered every question yet: wait for them.")
    elif pull["kind"] in ("fix", "change") and "reproduced" not in done:
        raise ToolError(
            f"Reproduce it first (reproduce): a test that fails on v{pull['base_version']}. "
            "Nothing in the copy changes before."
        )


def small_enough(agent_id: str, pull: dict, config: dict) -> None:
    """Raise ToolError if a fix or a change touches more than MAX_FIXED_STEPS steps of its base."""
    base = base_of(agent_id, pull)
    if pull["kind"] not in ("fix", "change") or base is None:
        return
    touched = artifacts.changed_steps(base["config"], config)
    if len(touched) > artifacts.MAX_FIXED_STEPS:
        names = ", ".join(facts.words(name) for name, _ in touched)
        raise ToolError(
            f"That would change {len(touched)} steps of v{base['number']} ({names}): a fix "
            f"changes {artifacts.MAX_FIXED_STEPS} at most. Change the step where it goes "
            "wrong, or add a rule on it instead."
        )


def may_change_test(pull: dict, test: dict, removing: bool) -> None:
    if pull["kind"] == "setup" and removing:
        raise ToolError(
            "A setup never takes a test out: rewrite it if it asks for more than the "
            "guidelines say, or change the agent."
        )
    if is_test_of(test, pull["number"]):
        raise ToolError(
            "That test reproduces what this pull request is for: it says what the agent must "
            "do, so it stays as it is. Change the agent."
        )
    if removing and not added_in(test, pull["number"]):
        raise ToolError(f"That test was not added in {store.label(pull['number'])}.")


def ready(agent_id: str, pull: dict) -> bool:
    """Whether the copy is at a point where its tests say something: drawn, with its
    questions answered, and (a fix, a change) with what it is for reproduced."""
    record = store.prosper.work_of(agent_id, pull["number"])
    if not pull["config"]["nodes"] or any(q["answer"] is None for q in record.get("questions", [])):
        return False
    return pull["kind"] not in ("fix", "change") or "reproduced" in record.get("built", [])


def ready_to_run(work: Work, pull: dict) -> None:
    """Raise ToolError if the copy is not ready for its suite, or the turn ran it enough."""
    may_edit(work, pull)
    if not pull["config"]["nodes"]:
        raise ToolError("There is nothing to test yet: draw the agent first.")
    if pull["kind"] == "setup":
        if store.get_run(work.agent_id, pull=work.number) is None:
            low, high = artifacts.SETUP_TESTS
            if not low <= len(pull["tests"]) <= high:
                raise ToolError(f"Write {low} to {high} tests first; it has {len(pull['tests'])}.")
        quoted = {artifacts.plain(r["source"].get("quote", "")) for r in pull["rules"]}
        answers = store.prosper.work_of(work.agent_id, work.number).get("questions", [])
        for question in answers:
            if question.get("setup") and artifacts.plain(question["answer"] or "") not in quoted:
                raise ToolError(
                    f'The clinic answered "{question["answer"]}": make it a rule on the step '
                    "it is about, quoting that answer, before the tests run."
                )
    if not pull["tests"]:
        raise ToolError("The copy has no tests.")
    if work.runs > MAX_ROUNDS:
        raise ToolError(
            f"That was your last round ({MAX_ROUNDS} after the first run): say what still "
            "fails and what the person could change."
        )


# ---- reproducing what a fix is for -------------------------------------------


def play(work: Work, version: dict, test: dict) -> list[dict]:
    """The test called REPEATS times on `version`, each call checked. Its cost is counted."""
    from api import checks  # who the calls talk to: the tests swap them for fakes

    results: list[dict] = []
    services = checks.services or simulate.Services()

    async def go() -> None:
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

    asyncio.run(go())
    model = version["config"].get("model", "")
    usd = 0.0
    for result in results:
        tokens = result["tokens"]
        usd += price(model, **tokens.get("agent", {}))
        for part in ("caller", "judge"):
            said = tokens.get(part, {})
            usd += price(prosper_model(), said.get("prompt", 0), said.get("completion", 0))
    work.model.add_cost(usd)
    return results


def passed(results: list[dict]) -> int:
    return sum(1 for result in results if result["passed"])


def how_it_went(results: list[dict]) -> list[str]:
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


def _before(version: dict, score: int, runs: int) -> dict:
    return {"before": {"version": version["number"], "passed": score, "runs": runs}}


def reproduce(work: Work, test: dict) -> str:
    """Play `test` on the base: kept as the copy's test of the issue if it fails; else one
    sharper try, and then the person is asked whether to go on."""
    pull = pull_of(work)
    subject, version = subject_of(work.agent_id, pull), base_of(work.agent_id, pull)
    if subject is None or version is None:
        raise ToolError("Only a fix or a change reproduces what it is for.")
    record = store.prosper.work_of(work.agent_id, work.number)
    if "reproduced" in record.get("built", []):
        raise ToolError("It is reproduced already: its test is in the copy. Change the agent now.")
    tries = record.get("tries", 0)
    if tries >= subject.tries:
        raise ToolError("No tries left: the person decides whether to go on.")
    try:
        artifacts.check_tests([test], version["config"])
    except ValueError as error:
        raise ToolError(str(error)) from error
    results = play(work, version, test)
    score, runs = passed(results), len(results)
    store.prosper.update(work.agent_id, work.number, tries=tries + 1)
    if verdict({"runs": results}, simulate.REPEATS) == "failing":
        kept = {"id": new_id(), **test, "source": subject.source(**_before(version, score, runs))}
        said = event(
            "reproduced",
            text=subject.failing(version, score, runs),
            test=kept["id"],
            version=version["number"],
            passed=score,
            total=runs,
            details=how_it_went(results),
        )
        store.prosper.change(
            work.agent_id, work.number, None, tests=[*pull["tests"], kept], step=said
        )
        store.prosper.mark_built(work.agent_id, work.number, "reproduced")
        failed_on = next(r for r in results if not r["passed"])
        return (
            f"Reproduced: it fails on v{version['number']}, {score}/{runs}. It is in the copy now "
            f"as the test of what this pull request is for.\nOne of its calls:\n"
            f"{facts.the_call(failed_on)}\nNow make the smallest change that makes it pass."
        )
    store.prosper.update(work.agent_id, work.number, candidate={"test": test, "passed": score})
    if tries + 1 < subject.tries:
        line = (
            f"A first test passed {score}/{runs} on v{version['number']}: trying a sharper caller"
        )
        store.prosper.log(work.agent_id, work.number, event("step", text=line))
        return (
            f"It passed {score} of {runs} calls on v{version['number']}: it does not reproduce "
            f"the problem.\nHow one of its calls went:\n{facts.the_call(results[0])}\n\n"
            "Write a sharper caller (one who does what the issue's callers did, at the moment "
            "they did it) with checks that catch exactly what went wrong, and try once more."
        )
    text = subject.passing(version, score, runs)
    store.prosper.log(
        work.agent_id, work.number, event("message", text=text, details=how_it_went(results))
    )
    question = {
        "text": f"Propose {subject.what()} anyway, with the test I wrote?",
        "options": [
            {"label": f"Yes, propose {subject.what()} anyway", "rule": None},
            {"label": "No, leave it as it is", "rule": None},
        ],
    }
    store.prosper.ask(work.agent_id, work.number, [question], kind="go_on")
    work.waiting = True
    return "It passes on the base too. The person is asked whether to go on: stop here."


def keep_anyway(agent_id: str, number: int) -> bool:
    """The person said to go on without a reproduction: the test that passed joins the copy.

    Returns whether it did; without the test (a record lost), it says so and stops.
    """
    pull = store.get_pull(agent_id, number)
    record = store.prosper.work_of(agent_id, number)
    version = base_of(agent_id, pull)
    candidate = record.get("candidate")
    if "reproduced" in record.get("built", []):
        return True
    if not candidate or version is None:
        text = (
            "I no longer have the test I wrote on the live version, so there is nothing to go "
            "on with. Tell me what to change, or close this pull request."
        )
        store.prosper.log(agent_id, number, event("message", text=text))
        store.prosper.set_state(agent_id, number, "done")
        return False
    subject = Subject(agent_id, pull)
    source = subject.source(**_before(version, candidate["passed"], simulate.REPEATS))
    kept = {"id": new_id(), **candidate["test"], "source": source}
    said = (
        f"Added the test anyway: {candidate['passed']}/{simulate.REPEATS} on v{version['number']}"
    )
    store.prosper.change(
        agent_id, number, None, tests=[*pull["tests"], kept], step=event("step", text=said)
    )
    store.prosper.mark_built(agent_id, number, "reproduced")
    return True


def leave_it(agent_id: str, number: int) -> None:
    """The person said not to go on: the copy stays as its base, and Prosper AI says so."""
    pull = store.get_pull(agent_id, number)
    text = (
        f"Left it as it is: v{pull['base_version']} stays unchanged. Close this pull request, "
        "or tell me what to change."
    )
    store.prosper.log(agent_id, number, event("message", text=text))
    store.prosper.set_state(agent_id, number, "done")


# ---- the copy's tests --------------------------------------------------------


def run(work: Work, test_id: Optional[str] = None) -> dict:
    """Run the copy's suite (or one test of it again) and wait for it. Returns the run."""
    from api import checks  # the API runs the checks; imported late, it also mounts this

    if test_id is None:
        checks.start(work.agent_id, pull=work.number)
    else:
        checks.start_test(work.agent_id, test_id, work.number, None)
    checks.finish(work.agent_id, work.number, CHECKS_WAIT)
    return store.get_run(work.agent_id, pull=work.number)


def failing_tests(run: Optional[dict]) -> dict:
    """The tests that failed in `run`, by id: their names. Flaky ones are not here."""
    run = run or {"tests": [], "repeats": 0}
    return {t["id"]: t["name"] for t in run["tests"] if verdict(t, run["repeats"]) == "failing"}


def flaky_on_base(agent_id: str, pull: dict) -> dict:
    """The tests that passed only 2 of 3 on the version the pull request is based on, by id."""
    base = base_of(agent_id, pull)
    run = store.get_run(agent_id, version=base["number"]) if base else None
    if run is None:
        return {}
    return {t["id"]: t["name"] for t in run["tests"] if verdict(t, run["repeats"]) == "flaky"}


def proved(agent_id: str, number: int) -> None:
    """The checks of a fix or a change pass: said, with its own test before and after."""
    pull = store.get_pull(agent_id, number)
    checks = pull["checks"]
    run = store.get_run(agent_id, pull=number) or {"tests": []}
    head = (
        f"Checks pass · {checks['passed']}/{checks['total']}, {checks['flaky']} flaky"
        if checks["flaky"]
        else f"All checks passed · {checks['total']}/{checks['total']}"
    )
    text = f"{head} · {simulate.REPEATS} runs each"
    test = next((t for t in pull["tests"] if is_test_of(t, number)), None)
    result = next((r for r in run["tests"] if test and r["id"] == test["id"]), None)
    more = {}
    if test is not None and result is not None:
        before = test["source"]["before"]
        text += (
            f" · the new test {before['passed']}/{before['runs']} on v{before['version']}"
            f" → {passed(result['runs'])}/{len(result['runs'])}"
        )
        more = {"test": test["id"]}
    counts = {key: checks[key] for key in ("passed", "flaky", "total")}
    store.prosper.log(agent_id, number, event("proved", text=text, **counts, **more))


def results(agent_id: str, pull: dict) -> str:
    """How the copy's latest run went, for the model: each test, and a call of each that failed.

    Tests already flaky on the base and the pull request's own test are said
    for what they are, so the model treats them as the brief says.
    """
    run = store.get_run(agent_id, pull=pull["number"])
    if run is None:
        return "Its tests have not run yet."
    flaky_before = flaky_on_base(agent_id, pull)
    base = f"v{pull['base_version']}"
    lines = []
    for result in run["tests"]:
        if result.get("skipped"):
            continue
        kind = verdict(result, run["repeats"])
        score = f"{passed(result['runs'])}/{len(result['runs'])}"
        line = f"- [{result['id']}] {result['name']} · {kind}, {score}"
        test = next((t for t in pull["tests"] if t["id"] == result["id"]), None)
        if test and is_test_of(test, pull["number"]):
            line += " · the test of what this pull request is for"
        if result["id"] in flaky_before and kind != "passed":
            line += f" · already flaky on {base} (2/3 there): not this change's doing"
        bad = [r for r in result["runs"] if not r["passed"]]
        if bad:
            line += f"\n{facts.the_call(bad[0])}"
        lines.append(line)
    checks = store.runs.summary(run)
    label = store.label(pull["number"])
    head = f"The tests of {label}, {run['repeats']} calls each: {facts.tally(checks)}."
    return f"{head}\n" + "\n".join(lines)


def test_call(agent_id: str, pull: dict, test_id: str, index: int) -> str:
    """One call of a test in the copy's latest run, whole."""
    run = store.get_run(agent_id, pull=pull["number"]) or {"tests": []}
    result = next((t for t in run["tests"] if t["id"] == test_id), None)
    if result is None or not result["runs"]:
        raise ToolError("That test has no calls in the latest run.")
    if not 1 <= index <= len(result["runs"]):
        raise ToolError(f"It has calls 1 to {len(result['runs'])}.")
    call = result["runs"][index - 1]
    return f"{result['name']}, call {index} of {len(result['runs'])}:\n" + facts.the_call(
        call, whole=True
    )
