#
# What Prosper AI writes about calls, one request each: who calls (a mix of
# callers for a batch), what it found in one call (its review), and whether a
# finding is a problem already tracked (grouping). For each: the JSON schema
# the model answers in and the check its answer must pass, as artifacts.py
# does for an agent.
#
# A finding points at the exact turn it is about, by its index in the
# transcript, and quotes words from that line; the quote is checked to be
# there, so the issue page can highlight the line a person has to read and
# never a sentence the model made up. The step of a finding is the step the
# agent was in when it said that line, read from the transcript rather than
# asked for, so the two cannot disagree.
#
# All pure functions: the tests run them without a model.
#

from store.calls import OUTCOMES
from store.issues import SEVERITIES

from .artifacts import Problems, _list, _object, _plain, sentences

CALLERS_PER_BATCH = (10, 12)
CHECKS_PER_CALL = (3, 8)
MAX_TITLE_CHARS = 80
MAX_LINE_CHARS = 240
NEW = 0  # the issue a finding opens, in a grouping answer

_TEXT = {"type": "string"}

CALLERS = _object(
    callers=_list(
        _object(
            name=_TEXT,
            kind={"type": "string", "enum": ["routine", "edge"]},
            situation=_TEXT,
        )
    )
)

AUDIT = _object(
    outcome={"type": "string", "enum": list(OUTCOMES)},
    checks=_list(_object(text=_TEXT, passed={"type": "boolean"}, rule=_TEXT)),
    findings=_list(
        _object(
            check=_TEXT,
            turn={"type": "integer"},
            quote=_TEXT,
            why=_TEXT,
            title=_TEXT,
            severity={"type": "string", "enum": list(SEVERITIES)},
            description=_TEXT,
        )
    ),
)

GROUPING = _object(
    placements=_list(_object(finding={"type": "integer"}, issue={"type": "integer"}))
)


def check_callers(answer: dict, count: tuple = CALLERS_PER_BATCH) -> None:
    """A batch of `count` (min, max) callers, distinct, mostly routine with a few edge cases."""
    callers = answer["callers"]
    problems = Problems()
    if not count[0] <= len(callers) <= count[1]:
        problems.found.append(f"Write {count[0]} to {count[1]} callers, not {len(callers)}.")
    names = [caller["name"].strip().lower() for caller in callers]
    if len(set(names)) != len(names):
        problems.found.append("Give every caller a different name.")
    edge = sum(1 for caller in callers if caller["kind"] == "edge")
    if len(callers) >= 4 and not 2 <= edge <= len(callers) // 2:
        problems.found.append(
            f"{edge} of {len(callers)} callers are edge cases: most calls a clinic gets are "
            "routine, so make 2 or more of them edge cases, and no more than half."
        )
    problems.raise_any()


def transcript_lines(transcript: list[dict]) -> str:
    """A call's transcript as the audit reads it: each line numbered, with its step."""
    return "\n".join(
        f"[{i}] {line['role']} · {line['node'] or 'start'}: {line['text']}"
        for i, line in enumerate(transcript)
    )


def check_audit(answer: dict, transcript: list[dict], rules: set) -> None:
    """Raise ValueError with every problem of a call's review.

    Each failed check has exactly one finding, and only failed checks do.
    `rules` are the ids of the agent's rules a check may name.
    """
    problems = Problems()
    checks = answer["checks"]
    low, high = CHECKS_PER_CALL
    if not low <= len(checks) <= high:
        problems.found.append(f"Apply {low} to {high} checks to the call, not {len(checks)}.")
    texts = [check["text"] for check in checks]
    if len(set(texts)) != len(texts):
        problems.found.append("Two checks have the same text: merge them.")
    for check in checks:
        if check["rule"] and check["rule"] not in rules:
            problems.found.append(
                f"Check '{check['text']}' names rule '{check['rule']}', which the agent does "
                f"not have. Use one of: {', '.join(sorted(rules)) or 'none'}, or ''."
            )
    failed = {check["text"] for check in checks if not check["passed"]}
    found = [finding["check"] for finding in answer["findings"]]
    for text in failed - set(found):
        problems.found.append(f"Check '{text}' failed: give it a finding.")
    for text in set(found) - failed:
        problems.found.append(
            f"A finding is for '{text}', which is not a failed check. A finding's "
            "`check` is the exact text of the check it failed."
        )
    if len(set(found)) != len(found):
        problems.found.append("Give each failed check one finding, not several.")
    for finding in answer["findings"]:
        problems.check(_check_finding, finding, transcript)
    problems.raise_any()


def _check_finding(finding: dict, transcript: list[dict]) -> None:
    turn = finding["turn"]
    if not 0 <= turn < len(transcript) or transcript[turn]["role"] != "agent":
        agent = [i for i, line in enumerate(transcript) if line["role"] == "agent"]
        raise ValueError(
            f"The finding '{finding['title']}' is on turn {turn}, which is not a line of the "
            f"agent. The agent's turns are: {', '.join(map(str, agent))}."
        )
    if _plain(finding["quote"]).strip(" .") not in _plain(transcript[turn]["text"]):
        raise ValueError(
            f"The quote of finding '{finding['title']}' is not in turn {turn} word for word. "
            "Copy words from that line exactly."
        )
    if len(finding["title"]) > MAX_TITLE_CHARS:
        raise ValueError(f"The title '{finding['title']}' is long: say it in a few plain words.")
    for key in ("why", "description"):
        text = finding[key]
        if len(sentences(text)) > 1 or len(text) > MAX_LINE_CHARS:
            raise ValueError(f"The {key} of finding '{finding['title']}' must be one sentence.")


def step_of_turn(transcript: list[dict], turn: int, initial: str) -> str:
    """The step the agent was in when it said line `turn`."""
    return transcript[turn]["node"] or initial


def check_grouping(answer: dict, candidates: dict) -> None:
    """Every finding placed once, in an issue it may join or NEW.

    `candidates` maps each finding's index to the numbers of the issues it may
    join (those still tracked).
    """
    problems = Problems()
    placed = [placement["finding"] for placement in answer["placements"]]
    if sorted(placed) != sorted(candidates):
        problems.found.append(
            f"Place every finding exactly once: {', '.join(map(str, sorted(candidates)))}."
        )
    for placement in answer["placements"]:
        allowed = candidates.get(placement["finding"], [])
        if placement["issue"] != NEW and placement["issue"] not in allowed:
            problems.found.append(
                f"Finding {placement['finding']} cannot join issue {placement['issue']}: "
                f"it may join {', '.join(map(str, allowed)) or 'none'}, or {NEW} for a new issue."
            )
    problems.raise_any()


def seconds(transcript: list[dict]) -> int:
    """How long the call would have taken, spoken: there was no audio to time.

    About 150 words a minute, plus a pause at every change of turn.
    """
    words = sum(len(line["text"].split()) for line in transcript)
    return max(5, round(words / 2.5 + 0.8 * len(transcript)))
