#
# What Prosper AI writes into an agent: its steps, its rules, its tests. For
# each: the JSON shape the model writes it in, the check it must pass, and the
# conversion into what the store keeps. Its tools (api/tools.py) run them on
# every edit, and say what they refuse back to the model.
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
# What Prosper AI writes is kept short and in the product's words (steps,
# "moves on", never edge or node), and that is checked too, not only asked
# for: a step's task is at most three short sentences, a rule is one, and an
# edit is held to that only where it changes something. Tests check what
# the guidelines (or the person's answers) ask for: 2 to 4 checks, at
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

MAX_QUESTIONS = 2  # asked about an agent already drawn
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

# The graph's words, which no one reading a rule, a task or a condition should
# meet: the UI says steps, "moves on when" and "ends the call".
_JARGON = re.compile(r"\b(edges?|nodes?|functions?|transitions?|go_to_\w+)\b", re.IGNORECASE)

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

MAX_FIRST_QUESTIONS = 3  # asked before anything is drawn
ANSWER = "your answer"  # the source a rule names when it comes from the clinic's answer
# A fix changes this many steps at most: more is a rewrite, not a fix.
MAX_FIXED_STEPS = 2


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


def _said(node: dict) -> tuple:
    # What a person reads of a step: its task, and when it moves on.
    return (_task(node), tuple(edge.get("description", "") for edge in node.get("edges", [])))


def check_words(text: str, what: str) -> None:
    """Raise ValueError if `text` speaks of the graph rather than in the product's words."""
    if found := _JARGON.search(text):
        raise ValueError(
            f'{what} says "{found.group()}": people read it, so say it in the product\'s words '
            '(a step, "moves on to", "ends the call"), never edge, node, function or transition.'
        )


def check_concise(config: dict, before: Optional[dict] = None) -> None:
    """Raise ValueError if a step's task is long, or its words are the graph's.

    With `before`, only for the steps whose task or conditions changed.
    """
    old = {node["name"]: _said(node) for node in before["nodes"]} if before else {}
    for node in config["nodes"]:
        task = _task(node)
        if before is not None and old.get(node["name"]) == _said(node):
            continue
        check_words(task, f"The task of step '{node['name']}'")
        for edge in node.get("edges", []):
            check_words(edge.get("description", ""), f"A condition of step '{node['name']}'")
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
    check_words(text, f"Rule '{text}'")


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


def plain(text: str) -> str:
    """`text` as a quote is compared: curly quotes straight, one case, single spaces."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


def check_rule(rule: dict, steps: set) -> Optional[str]:
    """Raise ValueError if the rule is not one short sentence on a step the agent has.

    Returns its step as stored, None for every step.
    """
    check_rule_text(rule["text"])
    step = step_of(rule["step"])
    if step is not None and step not in steps:
        raise ValueError(
            f"Rule '{rule['text']}' is for step '{rule['step']}', which the agent does not "
            f"have. Use one of: {', '.join(sorted(steps))}, or null for every step."
        )
    return step


def check_quote(rule: dict, sources: list[dict], answers: list[str]) -> dict:
    """The rule's source as stored, from the line it quotes: of the guidelines, word for word,
    or one of the clinic's `answers` (source "your answer"). Raises ValueError otherwise:
    a quote the model made up would point the person at a sentence nobody wrote."""
    if rule["source"] == ANSWER:
        if plain(rule["quote"]) not in {plain(a) for a in answers}:
            raise ValueError(
                f"Rule '{rule['text']}' quotes '{rule['quote']}', which is not one of the "
                f"clinic's answers: {', '.join(answers) or 'none'}."
            )
        return {"kind": "answer", "quote": rule["quote"]}
    texts = {source["name"]: plain(source["text"]) for source in sources}
    if rule["source"] not in texts:
        raise ValueError(
            f"Rule '{rule['text']}' quotes '{rule['source']}', which is not one of the "
            f"sources: {', '.join([*texts, ANSWER])}."
        )
    if plain(rule["quote"]).strip(" .") not in texts[rule["source"]]:
        raise ValueError(
            f"The quote of rule '{rule['text']}' is not in '{rule['source']}' word for "
            "word. Copy the line exactly as it is written there."
        )
    return {"kind": "guidelines", "file": rule["source"], "quote": rule["quote"]}


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


def check_questions(questions: list[dict], steps: Optional[set]) -> None:
    """Raise ValueError for questions that cannot be asked as they are.

    `steps`: the agent's, when it is drawn; None before, when there is nothing
    for an option's rule to go on yet, so an option is only what the clinic picks.
    """
    most = MAX_QUESTIONS if steps is not None else MAX_FIRST_QUESTIONS
    if len(questions) > most:
        raise ValueError(f"Ask {most} questions at most: only the ones that matter.")
    for question in questions:
        if not 2 <= len(question["options"]) <= 3:
            raise ValueError(f"Question '{question['text']}' needs 2 or 3 options.")
        for option in question["options"]:
            if option["rule"] is None:
                continue
            if steps is None:
                raise ValueError(
                    "Nothing is drawn yet: an option is only what the clinic picks. "
                    "Leave its rule null; their answer becomes rules once there are steps."
                )
            check_rule(option["rule"], steps)


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
