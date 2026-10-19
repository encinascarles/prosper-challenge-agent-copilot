#
# What Prosper AI writes, one artifact per request: the agent, its rules, its
# tests and its questions. For each: the JSON schema the model answers in, the
# check its answer must pass, and the conversion into what the store keeps.
#
# The agent is asked for in a shape of its own, close to AgentConfig but not
# AgentConfig itself. Structured Outputs in strict mode needs every object's
# keys to be known, and an edge's `properties` is a JSON-schema object keyed
# by field name, which strict mode cannot describe. So the model lists an
# edge's fields, and `to_config` turns them into `properties` and `required`.
# It also writes what a person never types: node names in snake_case, and each
# edge's function, `go_to_<target>`, as the editor generates it. The result is
# checked by AgentBuilder, exactly as a save is, plus the two things the editor
# only warns about but a call cannot get through: a step with no way out that
# does not end the call, and a flow with no end.
#
# Every rule quotes the line of the guidelines it comes from, and the quote is
# checked to be there, word for word: a quote the model made up would point the
# person at a sentence nobody wrote. A test's path checks must name steps and
# fields the agent has.
#
# What Prosper AI writes is kept short, and that is checked too, not only
# asked for: a step's task is at most three short sentences, a rule is one,
# and a change is held to that only where it changes something. Tests check
# what the guidelines (or the person's answers) ask for: 2 to 4 checks, at
# most one judged, and never style or wording, which no guideline states and
# a judge reads differently each time.
#
# All pure functions: the tests run them without a model.
#

import re
import unicodedata
from typing import Optional

from agent_builder import AgentBuilder
from agent_builder.schema import DEFAULT_MODEL, DEFAULT_VOICE_ID
from simulate.checks import parse, unknown_name

MAX_QUESTIONS = 2
MAX_TASK_SENTENCES = 3
MAX_TASK_CHARS = 360
MAX_RULE_CHARS = 200
SETUP_TESTS = (5, 7)
CHECKS_PER_TEST = (2, 4)
# Words that make a judged check about style rather than about what happens.
_STYLE = re.compile(
    r"\b(sentences?|words?|concise(ly)?|brief(ly)?|tone|polite(ly)?|friendly|warm(ly)?|"
    r"wording|phrasing|short (replies|answers|responses))\b",
    re.IGNORECASE,
)

_TEXT = {"type": "string"}
_STEP = {"type": ["string", "null"]}


def _object(**properties) -> dict:
    # Strict mode: every key required, nothing else allowed.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _list(items: dict) -> dict:
    return {"type": "array", "items": items}


# `options` last. With `required` after it, the model wanted to close the
# field there; strict mode refuses that, and the only thing left it could
# write was blank space, until the answer ran out of room (real changes cut
# off at 12,000 tokens). Ending on `options` lets it close where it wants to.
_FIELD = _object(
    name=_TEXT,
    description=_TEXT,
    type={"type": "string", "enum": ["string", "number", "boolean", "choice"]},
    required={"type": "boolean"},
    options=_list(_TEXT),
)
_EDGE = _object(description=_TEXT, target=_TEXT, fields=_list(_FIELD))
_NODE = _object(name=_TEXT, task=_TEXT, end={"type": "boolean"}, edges=_list(_EDGE))
AGENT = _object(persona=_TEXT, initial_node=_TEXT, nodes=_list(_NODE))

RULES = _object(rules=_list(_object(step=_STEP, text=_TEXT, source=_TEXT, quote=_TEXT)))

_TEST = _object(name=_TEXT, caller=_TEXT, checks=_list(_TEXT))
TESTS = _object(tests=_list(_TEST))

_OPTION = _object(label=_TEXT, rule=_object(step=_STEP, text=_TEXT))
QUESTIONS = _object(questions=_list(_object(text=_TEXT, options=_list(_OPTION))))
# Asked before anything is drawn, so an option is only what the clinic can pick:
# the answer shapes the agent, and becomes rules once there are steps to put them on.
FIRST_QUESTIONS = _object(questions=_list(_object(text=_TEXT, options=_list(_TEXT))))
MAX_FIRST_QUESTIONS = 3
ANSWER = "your answer"  # the source a rule names when it comes from the clinic's answer

# A change asked for in the pull request's conversation: the agent whole, as it
# should be after it, what to add to its rules and tests, and which of them to
# take out (by id: only those this pull request added can go).
CHANGE = _object(
    reply=_TEXT,
    agent=AGENT,
    rules=_list(_object(step=_STEP, text=_TEXT)),
    tests=_list(_TEST),
    remove=_list(_TEXT),
)


# A fix of an issue: the agent whole, as it should be after the smallest change
# that fixes it, and rules to add. No tests: the test that reproduces the
# issue is written first, on its own.
FIX = _object(reply=_TEXT, agent=AGENT, rules=_list(_object(step=_STEP, text=_TEXT)))
# A fix changes this many steps at most: more is a rewrite, not a fix.
MAX_FIXED_STEPS = 2
# The test that reproduces an issue, written from its calls.
REPRODUCE = _object(name=_TEXT, caller=_TEXT, checks=_list(_TEXT))

# Prosper AI checking its own draft after a run: a verdict per failing test,
# and what it changes for each.
VERDICTS = ("agent", "test", "gap")
REVIEW = _object(
    summary=_TEXT,
    verdicts=_list(
        _object(test=_TEXT, verdict={"type": "string", "enum": list(VERDICTS)}, why=_TEXT)
    ),
    agent=AGENT,
    rules=_list(_object(step=_STEP, text=_TEXT)),
    remove_rules=_list(_TEXT),
    tests=_list(_object(id=_TEXT, name=_TEXT, caller=_TEXT, checks=_list(_TEXT))),
    questions=_list(_object(text=_TEXT, options=_list(_OPTION))),
)


# ---- names -------------------------------------------------------------------


def to_name(text: str) -> str:
    """What the editor stores for a typed name: "Collect détails" is "collect_details"."""
    plain = unicodedata.normalize("NFD", text)
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")


def function_name(target: str, taken: set) -> str:
    """`go_to_<target>`, numbered when the node already has one: as frontend/src/draft/names.ts."""
    base = f"go_to_{re.sub(r'[^a-zA-Z0-9_-]+', '_', target) or 'next'}"[:64]
    n = 1
    while True:
        suffix = "" if n == 1 else f"_{n}"
        candidate = base[: 64 - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


# ---- the agent ---------------------------------------------------------------


def to_config(name: str, drafted: dict, model: str = DEFAULT_MODEL) -> dict:
    """The agent JSON for an agent the model drafted in the AGENT shape.

    The voice agent runs on its own model (gpt-4o for the sample), not on
    Prosper AI's: what calls need is latency, and what is tested is what runs.
    """
    names = {node["name"]: to_name(node["name"]) for node in drafted["nodes"]}
    nodes = []
    for node in drafted["nodes"]:
        taken: set = set()
        edges = []
        for edge in node["edges"]:
            target = names.get(edge["target"], to_name(edge["target"]))
            function = function_name(target, taken)
            taken.add(function)
            properties, required = {}, []
            for field in edge["fields"]:
                key = to_name(field["name"])
                prop = {"type": "string" if field["type"] == "choice" else field["type"]}
                if field["type"] == "choice":
                    prop["enum"] = field["options"]
                prop["description"] = field["description"]
                properties[key] = prop
                if field["required"]:
                    required.append(key)
            edges.append(
                {
                    "function": function,
                    "description": edge["description"],
                    "target": target,
                    **({"properties": properties, "required": required} if properties else {}),
                }
            )
        nodes.append(
            {
                "name": names[node["name"]],
                "task_messages": [{"role": "developer", "content": node["task"]}],
                **({"edges": edges} if edges else {}),
                **({"end": True} if node["end"] else {}),
            }
        )
    return {
        "name": name,
        "voice_id": DEFAULT_VOICE_ID,
        "model": model,
        "persona": drafted["persona"],
        "initial_node": names.get(drafted["initial_node"], to_name(drafted["initial_node"])),
        "nodes": nodes,
    }


def from_config(config: dict) -> dict:
    """An agent JSON in the AGENT shape, for a request that changes it."""
    nodes = []
    for node in config["nodes"]:
        edges = []
        for edge in node.get("edges", []):
            required = set(edge.get("required", []))
            fields = []
            for key, prop in edge.get("properties", {}).items():
                choice = "enum" in prop
                fields.append(
                    {
                        "name": key,
                        "description": prop.get("description", ""),
                        "type": "choice" if choice else prop.get("type", "string"),
                        "required": key in required,
                        "options": prop.get("enum", []),
                    }
                )
            edges.append(
                {"description": edge["description"], "target": edge["target"], "fields": fields}
            )
        task = "\n\n".join(m["content"] for m in node.get("task_messages", []))
        nodes.append(
            {"name": node["name"], "task": task, "end": node.get("end", False), "edges": edges}
        )
    persona = config.get("persona", "")
    return {"persona": persona, "initial_node": config["initial_node"], "nodes": nodes}


def keep_extras(config: dict, before: dict) -> dict:
    """`config` with what AGENT has no place for kept from `before`, step by step.

    A node's own role message and its actions are not in the shape the model
    rewrites; a change should not drop them from the steps it leaves alone,
    nor rename the functions of their edges.
    """
    old = {node["name"]: node for node in before.get("nodes", [])}
    nodes = []
    for node in config["nodes"]:
        was = old.get(node["name"], {})
        extras = {k: was[k] for k in ("role_message", "pre_actions", "post_actions") if k in was}
        nodes.append({**node, **extras, **_functions_kept(node, was)})
    kept = {k: before[k] for k in ("voice_id", "model") if k in before}
    return {**config, **kept, "nodes": nodes}


def _functions_kept(node: dict, was: dict) -> dict:
    """The node's edges with the function names they had, for edges to the same target.

    The shape the model writes has no function names, and `to_config` makes
    them `go_to_<target>`; an agent drawn by hand may have named them
    otherwise ("choose_intent"). A change to one step should not rename the
    functions of every other.
    """
    if "edges" not in node:
        return {}
    old = [edge for edge in was.get("edges", [])]
    names = {edge["function"] for edge in old}
    edges, taken = [], set()
    for edge in node["edges"]:
        same = next(
            (e for e in old if e["target"] == edge["target"] and e["function"] not in taken), None
        )
        function = same["function"] if same else edge["function"]
        if same is None and function in names:
            function = function_name(edge["target"], names | taken)
        taken.add(function)
        edges.append({**edge, "function": function})
    return {"edges": edges}


class Problems:
    """Every problem of an answer at once, so the model fixes them all in one go.

    Refusing on the first one sent the model back to fix that one, and it
    broke another on the way: three attempts went by on three different
    problems. `check` runs a check and keeps its sentence; `raise_any` raises
    them all together.
    """

    def __init__(self):
        self.found: list[str] = []

    def check(self, run, *args) -> None:
        try:
            run(*args)
        except ValueError as error:
            self.found.append(str(error))

    def raise_any(self) -> None:
        if self.found:
            listed = "\n".join(f"- {problem}" for problem in self.found)
            raise ValueError(
                f"{len(self.found)} problems:\n{listed}" if len(self.found) > 1 else self.found[0]
            )


def sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]


def _task(node: dict) -> str:
    return "\n\n".join(m["content"] for m in node.get("task_messages", []))


def check_concise(config: dict, before: Optional[dict] = None) -> None:
    """Raise ValueError if a step's task is long. With `before`, only for the tasks that changed."""
    old = {node["name"]: _task(node) for node in before["nodes"]} if before else {}
    for node in config["nodes"]:
        task = _task(node)
        if before is not None and old.get(node["name"]) == task:
            continue
        count = len(sentences(task))
        if count > MAX_TASK_SENTENCES or len(task) > MAX_TASK_CHARS:
            raise ValueError(
                f"The task of step '{node['name']}' is {count} sentences ({len(task)} "
                f"characters): keep it to {MAX_TASK_SENTENCES} short sentences at most. "
                "What holds on every step belongs in a rule."
            )


def check_rule_text(text: str) -> None:
    if len(sentences(text)) > 1 or len(text) > MAX_RULE_CHARS:
        raise ValueError(f"Rule '{text}' must be one short sentence.")


def check_agent(config: dict) -> None:
    """Raise ValueError with what is wrong with `config`, as a save would say it, or more."""
    builder = AgentBuilder.from_dict(config)
    ends = [node for node in builder.config.nodes if node.end]
    if not ends:
        raise ValueError("No step ends the call: mark the goodbye step with end true.")
    for node in builder.config.nodes:
        # The editor lets nothing lead into the start step (a call begins
        # there), and draws such an edge as not connected.
        for edge in node.edges:
            if edge.target == builder.config.initial_node:
                raise ValueError(
                    f"Edge '{edge.function}' of step '{node.name}' goes back to the start step "
                    f"'{edge.target}', and nothing may lead into the start step. Point it at "
                    "the step that handles what the caller wants next."
                )
        if node.end and node.edges:
            raise ValueError(f"Step '{node.name}' ends the call, so it cannot have edges.")
        if not node.end and not node.edges:
            raise ValueError(
                f"Step '{node.name}' has no edges and does not end the call: a call would "
                "stay there for good. Give it an edge, or make it end the call."
            )


# ---- rules -------------------------------------------------------------------


def step_of(step: Optional[str]) -> Optional[str]:
    """A rule's step as stored: the model may write "Offer times" for `offer_times`."""
    return None if step is None or not step.strip() else to_name(step)


def _plain(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


def _check_step(rule: dict, steps: set) -> None:
    check_rule_text(rule["text"])
    step = step_of(rule["step"])
    if step is not None and step not in steps:
        raise ValueError(
            f"Rule '{rule['text']}' is for step '{rule['step']}', which the agent does not "
            f"have. Use one of: {', '.join(sorted(steps))}, or null for every step."
        )


def check_first_questions(answer: dict) -> None:
    problems = Problems()
    if len(answer["questions"]) > MAX_FIRST_QUESTIONS:
        problems.found.append(f"Ask {MAX_FIRST_QUESTIONS} questions at most: the ones that matter.")
    for question in answer["questions"]:
        if not 2 <= len(question["options"]) <= 3:
            problems.found.append(f"Question '{question['text']}' needs 2 or 3 options.")
    problems.raise_any()


def check_rules(answer: dict, config: dict, sources: list[dict], answers: tuple = ()) -> None:
    """Every rule traced to a line of the guidelines, or to one of the clinic's `answers`.

    Each answer becomes at least one rule, quoting it, on the step it is about.
    """
    problems = Problems()
    for rule in answer["rules"]:
        if rule["source"] == ANSWER:
            problems.check(_check_answer_rule, rule, config, answers)
        else:
            problems.check(_check_rule, rule, config, sources)
    quoted = {_plain(r["quote"]) for r in answer["rules"] if r["source"] == ANSWER}
    for given in answers:
        if _plain(given) not in quoted:
            problems.found.append(
                f"The clinic answered '{given}': write it as a rule on the step it is about, "
                f"with source '{ANSWER}' and that answer as its quote."
            )
    problems.raise_any()


def _check_answer_rule(rule: dict, config: dict, answers: tuple) -> None:
    _check_step(rule, {node["name"] for node in config["nodes"]})
    if _plain(rule["quote"]) not in {_plain(a) for a in answers}:
        raise ValueError(
            f"Rule '{rule['text']}' quotes '{rule['quote']}', which is not one of the clinic's "
            f"answers: {', '.join(answers) or 'none'}."
        )


def _check_rule(rule: dict, config: dict, sources: list[dict]) -> None:
    steps = {node["name"] for node in config["nodes"]}
    texts = {source["name"]: _plain(source["text"]) for source in sources}
    _check_step(rule, steps)
    if rule["source"] not in texts:
        raise ValueError(
            f"Rule '{rule['text']}' quotes '{rule['source']}', which is not one of the "
            f"sources: {', '.join(texts)}."
        )
    if _plain(rule["quote"]).strip(" .") not in texts[rule["source"]]:
        raise ValueError(
            f"The quote of rule '{rule['text']}' is not in '{rule['source']}' word for "
            "word. Copy the line exactly as it is written there."
        )


def rules_from(answer: dict, pull: int) -> list[dict]:
    """The rules of an answer to RULES, each with its source: a line of the guidelines."""
    return [
        {
            "step": step_of(rule["step"]),
            "text": rule["text"],
            "source": (
                {"kind": "answer", "pull": pull, "quote": rule["quote"]}
                if rule["source"] == ANSWER
                else {
                    "kind": "guidelines",
                    "pull": pull,
                    "file": rule["source"],
                    "quote": rule["quote"],
                }
            ),
        }
        for rule in answer["rules"]
    ]


# ---- tests -------------------------------------------------------------------


def _names(config: dict) -> tuple[list[str], list[str]]:
    steps = [node["name"] for node in config["nodes"]]
    fields = [
        key
        for node in config["nodes"]
        for edge in node.get("edges", [])
        for key in edge.get("properties", {})
    ]
    return steps, fields


def check_tests(tests: list[dict], config: dict, count: Optional[tuple] = None) -> None:
    """Raise ValueError for a test that cannot be read as meant. `count`: (min, max) tests."""
    if count and not count[0] <= len(tests) <= count[1]:
        raise ValueError(f"Write {count[0]} to {count[1]} tests, not {len(tests)}.")
    steps, fields = _names(config)
    problems = Problems()
    for test in tests:
        problems.check(_check_test, test, steps, fields)
    problems.raise_any()


def _check_test(test: dict, steps: list, fields: list) -> None:
    low, high = CHECKS_PER_TEST
    name = test["name"]
    if not low <= len(test["checks"]) <= high:
        given = len(test["checks"])
        raise ValueError(f"Test '{name}' has {given} checks: give it {low} to {high}.")
    judged = []
    for line in test["checks"]:
        if problem := unknown_name(line, steps, fields):
            raise ValueError(
                f"In test '{name}': {problem} A path check is only 'Reaches <step>', "
                "'Ends the call' or '<field> is recorded'; anything longer is judged."
            )
        if parse(line, steps, fields)["kind"] == "judged":
            judged.append(line)
            if _STYLE.search(line):
                raise ValueError(
                    f"In test '{name}', '{line}' checks style or wording, which the "
                    "guidelines do not ask for: check what happens in the call instead."
                )
    if len(judged) > 1:
        raise ValueError(
            f"Test '{name}' has {len(judged)} judged checks: keep the one it is about, "
            "and make the rest path checks (Reaches, Ends the call, is recorded)."
        )


# ---- questions ---------------------------------------------------------------


def check_questions(answer: dict, config: dict) -> None:
    steps = {node["name"] for node in config["nodes"]}
    if len(answer["questions"]) > MAX_QUESTIONS:
        raise ValueError(f"Ask {MAX_QUESTIONS} questions at most: only the ones that matter.")
    for question in answer["questions"]:
        if not 2 <= len(question["options"]) <= 3:
            raise ValueError(f"Question '{question['text']}' needs 2 or 3 options.")
        for option in question["options"]:
            check_rule_text(option["rule"]["text"])
            step = step_of(option["rule"]["step"])
            if step is not None and step not in steps:
                raise ValueError(
                    f"The rule of option '{option['label']}' is for step '{step}', which the "
                    f"agent does not have. Use one of: {', '.join(sorted(steps))}, or null."
                )


# ---- a change ----------------------------------------------------------------


def check_change(answer: dict, name: str, before: dict, removable: set = frozenset()) -> dict:
    """The agent JSON the change makes. Raises ValueError like the checks above.

    `removable` are the ids of the rules and tests the change may take out.
    """
    for item in answer.get("remove", []):
        if item not in removable:
            raise ValueError(
                f"'{item}' is not the id of a rule or test that can be taken out. "
                f"Those that can: {', '.join(sorted(removable)) or 'none'}."
            )
    config = keep_extras(to_config(name, answer["agent"]), before)
    check_agent(config)
    problems = Problems()
    problems.check(check_concise, config, before)
    steps = {node["name"] for node in config["nodes"]}
    for rule in answer["rules"]:
        problems.check(_check_step, rule, steps)
    for test in answer["tests"]:
        problems.check(check_tests, [test], config)
    problems.raise_any()
    return config


# ---- checking its own draft --------------------------------------------------


def check_review(
    answer: dict, failing: dict, before: dict, removable: set, kept: set = frozenset()
) -> dict:
    """The agent JSON a review makes. Raises ValueError like the checks above.

    `failing` maps the failing tests' ids to their names: each gets exactly
    one verdict, and only a test judged too strict is rewritten. A test is
    never taken out. `removable` are the rules the review may take out. `kept`
    are tests never rewritten: the one that reproduces the issue a fix is for.
    """
    verdicts = {}
    for item in answer["verdicts"]:
        if item["test"] not in failing:
            raise ValueError(
                f"'{item['test']}' is not a failing test. Failing: {', '.join(sorted(failing))}."
            )
        if item["test"] in kept and item["verdict"] == "test":
            raise ValueError(
                f"Test '{item['test']}' reproduces the issue this pull request fixes: it says "
                "what the agent must do. The agent is what is wrong."
            )
        verdicts[item["test"]] = item["verdict"]
    if missing := set(failing) - set(verdicts):
        raise ValueError(f"Give a verdict for every failing test; missing: {', '.join(missing)}.")
    rewritten = {test["id"] for test in answer["tests"]}
    too_strict = {test for test, verdict in verdicts.items() if verdict == "test"}
    if rewritten != too_strict:
        raise ValueError(
            "Rewrite exactly the tests whose verdict is 'test', by their id: "
            f"{', '.join(sorted(too_strict)) or 'none'}."
        )
    for item in answer["remove_rules"]:
        if item not in removable:
            raise ValueError(f"'{item}' is not the id of a rule that can be taken out.")
    config = keep_extras(to_config(before["name"], answer["agent"]), before)
    check_agent(config)
    problems = Problems()
    problems.check(check_concise, config, before)
    steps = {node["name"] for node in config["nodes"]}
    for rule in answer["rules"]:
        problems.check(_check_step, rule, steps)
    for test in answer["tests"]:
        problems.check(check_tests, [test], config)
    problems.check(check_questions, {"questions": answer["questions"]}, config)
    problems.raise_any()
    if "agent" in verdicts.values() and not (
        config != before or answer["rules"] or answer["remove_rules"]
    ):
        raise ValueError("A verdict says the agent is wrong, but nothing in the agent changed.")
    if "gap" in verdicts.values() and not answer["questions"]:
        raise ValueError("A verdict says the guidelines leave a gap: ask about it.")
    return config


# ---- a fix -------------------------------------------------------------------


def changed_steps(before: dict, after: dict) -> list[tuple[str, str]]:
    """The steps a change touches, each with what: "added", "removed", "task" or "edges"."""
    old = {node["name"]: node for node in before["nodes"]}
    new = {node["name"]: node for node in after["nodes"]}
    changes = [(name, "removed") for name in old if name not in new]
    for name, node in new.items():
        if name not in old:
            changes.append((name, "added"))
        elif _task(node) != _task(old[name]):
            changes.append((name, "task"))
        elif (node.get("edges", []), node.get("end", False)) != (
            old[name].get("edges", []),
            old[name].get("end", False),
        ):
            changes.append((name, "edges"))
    return changes


def check_fix(answer: dict, before: dict) -> dict:
    """The agent JSON a fix makes. Raises ValueError like a change, and if it is not small.

    It must change something (a step or a rule), and at most MAX_FIXED_STEPS steps.
    """
    config = check_change({**answer, "tests": [], "remove": []}, before["name"], before)
    touched = changed_steps(before, config)
    persona = config.get("persona") != before.get("persona")
    if not touched and not answer["rules"] and not persona:
        raise ValueError("Nothing changed: the fix must change a step, an edge or add a rule.")
    if len(touched) > MAX_FIXED_STEPS:
        names = ", ".join(name for name, _ in touched)
        raise ValueError(
            f"The fix changes {len(touched)} steps ({names}): change the one where it goes "
            f"wrong, {MAX_FIXED_STEPS} at most, or add a rule on that step instead."
        )
    return config


def check_reproduction(answer: dict, config: dict) -> None:
    """A test that reproduces an issue reads like any test, with a judged check or a path one."""
    check_tests([answer], config)
