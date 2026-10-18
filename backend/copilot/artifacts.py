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
# All pure functions: the tests run them without a model.
#

import re
import unicodedata
from typing import Optional

from agent_builder import AgentBuilder
from agent_builder.schema import DEFAULT_MODEL, DEFAULT_VOICE_ID
from simulate.checks import unknown_name

MAX_QUESTIONS = 2

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


_FIELD = _object(
    name=_TEXT,
    description=_TEXT,
    type={"type": "string", "enum": ["string", "number", "boolean", "choice"]},
    options=_list(_TEXT),
    required={"type": "boolean"},
)
_EDGE = _object(description=_TEXT, target=_TEXT, fields=_list(_FIELD))
_NODE = _object(name=_TEXT, task=_TEXT, end={"type": "boolean"}, edges=_list(_EDGE))
AGENT = _object(persona=_TEXT, initial_node=_TEXT, nodes=_list(_NODE))

RULES = _object(rules=_list(_object(step=_STEP, text=_TEXT, source=_TEXT, quote=_TEXT)))

_TEST = _object(name=_TEXT, caller=_TEXT, checks=_list(_TEXT))
TESTS = _object(tests=_list(_TEST))

_OPTION = _object(label=_TEXT, rule=_object(step=_STEP, text=_TEXT))
QUESTIONS = _object(questions=_list(_object(text=_TEXT, options=_list(_OPTION))))

# A change asked for in the pull request's conversation: the agent whole, as it
# should be after it, and what to add to its rules and tests.
CHANGE = _object(
    reply=_TEXT,
    agent=AGENT,
    rules=_list(_object(step=_STEP, text=_TEXT)),
    tests=_list(_TEST),
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
                        "options": prop.get("enum", []),
                        "required": key in required,
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
    rewrites; a change should not drop them from the steps it leaves alone.
    """
    old = {node["name"]: node for node in before.get("nodes", [])}
    nodes = []
    for node in config["nodes"]:
        was = old.get(node["name"], {})
        extras = {k: was[k] for k in ("role_message", "pre_actions", "post_actions") if k in was}
        nodes.append({**node, **extras})
    kept = {k: before[k] for k in ("voice_id", "model") if k in before}
    return {**config, **kept, "nodes": nodes}


def check_agent(config: dict) -> None:
    """Raise ValueError with what is wrong with `config`, as a save would say it, or more."""
    builder = AgentBuilder.from_dict(config)
    ends = [node for node in builder.config.nodes if node.end]
    if not ends:
        raise ValueError("No step ends the call: mark the goodbye step with end true.")
    for node in builder.config.nodes:
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
    step = step_of(rule["step"])
    if step is not None and step not in steps:
        raise ValueError(
            f"Rule '{rule['text']}' is for step '{rule['step']}', which the agent does not "
            f"have. Use one of: {', '.join(sorted(steps))}, or null for every step."
        )


def check_rules(answer: dict, config: dict, sources: list[dict]) -> None:
    steps = {node["name"] for node in config["nodes"]}
    texts = {source["name"]: _plain(source["text"]) for source in sources}
    for rule in answer["rules"]:
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
            "source": {
                "kind": "guidelines",
                "pull": pull,
                "file": rule["source"],
                "quote": rule["quote"],
            },
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


def check_tests(tests: list[dict], config: dict) -> None:
    steps, fields = _names(config)
    for test in tests:
        if not test["checks"]:
            raise ValueError(f"Test '{test['name']}' has no checks.")
        for line in test["checks"]:
            if problem := unknown_name(line, steps, fields):
                raise ValueError(f"In test '{test['name']}': {problem}")


# ---- questions ---------------------------------------------------------------


def check_questions(answer: dict, config: dict) -> None:
    steps = {node["name"] for node in config["nodes"]}
    if len(answer["questions"]) > MAX_QUESTIONS:
        raise ValueError(f"Ask {MAX_QUESTIONS} questions at most: only the ones that matter.")
    for question in answer["questions"]:
        if not 2 <= len(question["options"]) <= 3:
            raise ValueError(f"Question '{question['text']}' needs 2 or 3 options.")
        for option in question["options"]:
            step = step_of(option["rule"]["step"])
            if step is not None and step not in steps:
                raise ValueError(
                    f"The rule of option '{option['label']}' is for step '{step}', which the "
                    f"agent does not have. Use one of: {', '.join(sorted(steps))}, or null."
                )


# ---- a change ----------------------------------------------------------------


def check_change(answer: dict, name: str, before: dict) -> dict:
    """The agent JSON the change makes. Raises ValueError like the checks above."""
    config = keep_extras(to_config(name, answer["agent"]), before)
    check_agent(config)
    steps = {node["name"] for node in config["nodes"]}
    for rule in answer["rules"]:
        _check_step(rule, steps)
    check_tests(answer["tests"], config)
    return config
