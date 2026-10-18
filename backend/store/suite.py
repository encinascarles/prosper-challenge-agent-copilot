#
# Rules and tests — what an agent must do, kept with each copy of it.
#
# A rule is a short instruction for the agent's prompt, on every step or on one:
#   { id, step: "<node name>" | null, text, source }
# A test is a simulated call with what must happen in it, one check per line:
#   { id, name, caller, checks: ["Reaches confirm", "Ends the call", …], source }
# `source` says where it came from: { kind: "manual" } for one written by hand,
# with `pull` set to the pull request it was added in.
#
# Both travel with a copy of the agent, next to its config and layout and never
# inside its JSON: a pull request carries its own, a merge puts them live with
# the rest, and a version keeps the ones it was merged with. A pull request can
# only add rules and tests, and take out again those it added itself; that is
# what makes replaying it on a newer version simple (`rebase`).
#
# A rule names its step, so it follows the step: renamed with it, and dropped
# with it when the step is removed, like the step's position in the layout.
#

import uuid
from typing import Optional


def new_id() -> str:
    # Short: it is only unique within one agent's rules or tests.
    return uuid.uuid4().hex[:10]


def manual(pull: Optional[int]) -> dict:
    return {"kind": "manual", **({"pull": pull} if pull else {})}


def added_in(item: dict, pull: int) -> bool:
    """Whether the rule or test was added in pull request `pull`."""
    return item.get("source", {}).get("pull") == pull


def prune_rules(rules: list, config: dict) -> list:
    """`rules` without those for a step `config` does not have."""
    names = {node["name"] for node in config["nodes"]}
    return [rule for rule in rules if rule["step"] is None or rule["step"] in names]


def rename_rules(rules: list, renames: dict) -> list:
    """`rules` with their steps renamed as `renames` says: { old name: new name }."""
    return [{**rule, "step": renames.get(rule["step"], rule["step"])} for rule in rules]


def rebase(own: list, onto: list) -> list:
    """The rules or tests of a pull request replayed on a version's: `onto`, then its own."""
    ids = {item["id"] for item in onto}
    return [*onto, *(item for item in own if item["id"] not in ids)]
