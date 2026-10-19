#
# Calls coming in, and Prosper AI reading every one of them.
#
# There is no real call data, so a batch of calls is played on demand:
#
#   pick the callers     one request: a realistic mix for this clinic, from its
#                        guidelines and its agent (most routine, a few of the
#                        edge cases a front desk really gets)
#   -> make the calls    each a simulated caller on the live version, through
#                        the same text pipeline as the tests (simulate/), all
#                        at once, a moment apart, stored as each one ends
#   -> review each call  one request per call, as soon as it ends: the checks
#                        Prosper AI applied, what went wrong and on which turn
#   -> group findings    a finding joins a tracked issue with the same problem,
#                        or opens a new one
#
# Reviews run in parallel, but grouping takes one call at a time: two calls
# with the same new problem would otherwise each open an issue for it. A
# grouping request is only made when there is an issue to join. Any tracked
# issue may be joined, or one a fix resolved (a call on the fixed version opens
# it again), not only one in the finding's step: in real batches the
# same problem (a detail never confirmed) showed up on the turn of whichever
# step the agent was in, and keeping steps apart split it into two issues.
#
# A batch runs in a thread of its own with its own event loop, like the
# checks: the voice calls on the server's loop never wait behind it. What each
# part costs (the callers, the calls, the reviews) is added to the batch as it
# is spent.
#

import asyncio
import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from loguru import logger

import store
from agent_builder import AgentBuilder
from simulate.suite import prosper_model
from simulate.text_call import TextCall

from . import artifacts, audit
from .llm import LLM, price

# Who Prosper AI talks to. The tests swap it for a scripted model.
new_llm: Callable[[], LLM] = LLM

# Seconds between one call starting and the next: calls come in, not all at once.
STAGGER = 1.5
# Caller lines before a call is cut. Tests allow more, for a caller who
# corrects themselves; a real caller stuck in a loop hangs up sooner, and a
# stuck call would otherwise be the most expensive call of the batch.
MAX_TURNS = 12
_ENDED = {
    "agent_ended": "the agent ended it",
    "caller_hung_up": "the caller hung up",
    "turn_cap": "it never ended: cut after too many turns",
    "stuck": "the agent stopped answering",
    "end_not_reached": "the goodbye step spoke but the call did not end",
}

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="calls")
_jobs: list[Future] = []
_lock = threading.Lock()
_grouping = threading.Lock()


def play(agent_id: str, services, count: Optional[tuple] = None) -> dict:
    """Start a batch of `count` (min, max) simulated calls on the live version. Returns it.

    Raises NotFound, or Conflict if the agent is not live or a batch is going.
    `services` is who the calls talk to (simulate.Services, or fakes).
    """
    count = count or audit.CALLERS_PER_BATCH
    batch = store.calls.start_play(agent_id)
    future = _pool.submit(_guarded, agent_id, batch, services, count)
    with _lock:
        _jobs[:] = [job for job in _jobs if not job.done()] + [future]
    return batch


def wait(timeout: float = 60) -> None:
    """Wait for the batches in progress to finish. For tests."""
    with _lock:
        jobs = list(_jobs)
    for job in jobs:
        job.result(timeout)


def _guarded(agent_id: str, batch: dict, services, count: tuple) -> None:
    try:
        _play(agent_id, batch, services, count)
        store.calls.update_play(batch["id"], state="done")
    except Exception as error:  # noqa: BLE001 - said on the Calls page, never lost in a thread
        logger.exception(f"Calls on agent {agent_id} did not finish")
        reason = str(error) or type(error).__name__
        try:
            store.calls.update_play(batch["id"], state="failed", error=reason[:200])
        except Exception:  # noqa: BLE001 - the agent was deleted meanwhile
            pass
    finally:
        logger.info(f"Calls on agent {agent_id} spent: {store.calls.latest_play(agent_id)}")


def _play(agent_id: str, batch: dict, services, count: tuple) -> None:
    version = store.get_version(agent_id, batch["version"])
    context = _context(agent_id, version)
    llm = new_llm()
    try:
        answer = llm.ask(
            "callers",
            f"{context}\n\nWrite {count[0]} to {count[1]} callers.",
            audit.CALLERS,
            lambda a: audit.check_callers(a, count),
        )
    finally:
        store.calls.spend(batch["id"], "callers", llm.usage["usd"])
    store.calls.update_play(batch["id"], callers=len(answer["callers"]))
    asyncio.run(_calls(agent_id, batch, version, context, answer["callers"], services))


async def _calls(agent_id: str, batch: dict, version: dict, context: str, callers, services):
    builder = AgentBuilder.from_dict(version["config"], version["rules"])
    model = builder.config.model
    rules = {rule["id"] for rule in version["rules"]}

    async def one(index: int, caller: dict) -> None:
        await asyncio.sleep(index * STAGGER)
        person = services.caller(caller["situation"])
        try:
            call = await TextCall(builder, services.llm(model)).run(person, MAX_TURNS)
        except Exception:  # noqa: BLE001 - one call that breaks is not the batch
            logger.exception(f"A call from {caller['name']} did not run")
            return
        said = getattr(person, "tokens", {})
        usage = {
            "agent": round(price(model, **call["tokens"]), 4),
            "caller": round(
                price(prosper_model(), said.get("prompt", 0), said.get("completion", 0)), 4
            ),
        }
        store.calls.spend(batch["id"], "calls", usage["agent"] + usage["caller"])
        call_id = store.calls.add_call(
            agent_id,
            batch["id"],
            version["number"],
            caller["name"],
            caller["situation"],
            call,
            audit.seconds(call["transcript"]),
            usage,
        )
        await asyncio.to_thread(
            review, agent_id, call_id, caller["name"], call, version, context, rules, batch["id"]
        )

    await asyncio.gather(*(one(i, caller) for i, caller in enumerate(callers)))


def review(
    agent_id: str,
    call_id: int,
    caller: str,
    call: dict,
    version: dict,
    context: str,
    rules: set,
    batch: Optional[int] = None,
) -> None:
    """Prosper AI reviews the call and files what went wrong into issues. Never raises."""
    llm = new_llm()
    transcript = call["transcript"]
    try:
        path = " > ".join(step["node"] for step in call["path"]) or "nowhere"
        content = (
            f"{context}\n\nThe call, from {caller}. How it ended: "
            f"{_ENDED.get(call['ended'], call['ended'])}. Steps: {path}.\n\n"
            f"Transcript:\n{audit.transcript_lines(transcript)}"
        )
        answer = llm.ask(
            "audit", content, audit.AUDIT, lambda a: audit.check_audit(a, transcript, rules)
        )
        initial = version["config"]["initial_node"]
        findings = [
            {**finding, "step": audit.step_of_turn(transcript, finding["turn"], initial)}
            for finding in answer["findings"]
        ]
        with _grouping:
            for finding, issue in zip(findings, _group(llm, agent_id, findings), strict=True):
                store.issues.file_finding(agent_id, call_id, caller, finding, issue)
        store.calls.record_review(call_id, answer["outcome"], answer["checks"], llm.usage["usd"])
    except Exception:  # noqa: BLE001 - the call stays, marked as not reviewed
        logger.exception(f"Prosper AI could not review call {call_id}")
        store.calls.review_failed(call_id)
    finally:
        if batch is not None:
            store.calls.spend(batch, "reviews", llm.usage["usd"])


def _group(llm: LLM, agent_id: str, findings: list[dict]) -> list[Optional[int]]:
    """The issue each finding joins, by number, or None for a new one."""
    tracked = store.issues.joinable(agent_id)
    if not tracked:
        return [None] * len(findings)
    candidates = {i: [issue["number"] for issue in tracked] for i in range(len(findings))}
    issues = "\n".join(
        f"- [{issue['number']}] {issue['step']} · {issue['title']}: {issue['description']}"
        f"{_fixed(issue)}"
        for issue in tracked
    )
    found = "\n".join(
        f"- [{i}] {finding['step']} · {finding['title']}: {finding['description']}"
        for i, finding in enumerate(findings)
    )
    answer = llm.ask(
        "grouping",
        f"The issues being tracked:\n{issues}\n\nThe new findings:\n{found}",
        audit.GROUPING,
        lambda a: audit.check_grouping(a, candidates),
    )
    placed = {p["finding"]: p["issue"] for p in answer["placements"]}
    return [placed.get(i) or None for i in range(len(findings))]


def _fixed(issue: dict) -> str:
    # Still the same problem if it comes back: the grouping should know it was fixed.
    fixed = issue.get("fixed")
    return f" (fixed in v{fixed['version']})" if fixed else ""


def _context(agent_id: str, version: dict) -> str:
    """What a request about this agent's calls reads first: its guidelines, agent and rules.

    The same for every call of a batch and written first, so the model's
    prompt cache serves it to every review after the first.
    """
    sources, answers = store.prosper.guidelines(agent_id)
    if sources:
        texts = "\n\n".join(f"=== {s['name']} ===\n{s['text']}" for s in sources)
        guidelines = f"The clinic's guidelines:\n\n{texts}"
    else:
        guidelines = "No written guidelines: the agent's steps and rules are what the clinic asked."
    given = "\n".join(f'- "{q["text"]}" → "{q["answer"]}"' for q in answers)
    rules = "\n".join(
        f"- [{rule['id']}] {rule['step'] or 'every step'}: {rule['text']}{_quoted(rule)}"
        for rule in version["rules"]
    )
    agent = json.dumps(artifacts.from_config(version["config"]), indent=1)
    return (
        f"{guidelines}\n\nThe clinic's answers to Prosper AI's questions:\n{given or '(none)'}"
        f"\n\nThe agent, v{version['number']} (it has no calendar and no patient records):\n"
        f"{agent}\n\nIts rules:\n{rules or '(none)'}"
    )


def _quoted(rule: dict) -> str:
    quote = (rule.get("source") or {}).get("quote")
    return f' (from: "{quote}")' if quote else ""
