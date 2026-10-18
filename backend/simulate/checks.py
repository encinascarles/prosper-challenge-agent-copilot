#
# Checks — what must happen in a test's call, one line each, and how each is
# decided.
#
# A line is read into one of four kinds. Three are decided from the call's
# path, exactly and for free:
#   "Reaches <step>"        the call entered that step
#   "Ends the call"         the agent ended it (not the caller hanging up)
#   "<field> is recorded"   an edge collected that field, with a value
# Anything else is judged: a model reads the transcript and answers yes or no,
# with one line saying why. Path checks are the stable ones; judged checks
# cover what a path cannot see (what was said, and how).
#
# Steps and fields are written as people read them ("Offer times", "Full
# name") and match the names in the agent ("offer_times", "full_name").
#

import json
import re
from typing import Optional

from openai import AsyncOpenAI

_REACHES = re.compile(r"reaches (?:the )?(?P<name>.+?)(?: step)?", re.IGNORECASE)
_ENDS = re.compile(r"(?:the agent )?ends the call", re.IGNORECASE)
_RECORDED = re.compile(r"(?:the )?(?P<name>.+?) is recorded", re.IGNORECASE)

_ENDINGS = {
    "caller_hung_up": "The caller hung up; the agent never ended the call.",
    "turn_cap": "Still going when the call was cut.",
    "stuck": "The agent stopped answering.",
    "end_not_reached": "The end step spoke, but the call did not end.",
    "error": "The call did not run.",
}

_JUDGE = (
    "You check one phone call between an automated assistant and a caller against one "
    "statement about it. Decide only from the transcript. Answer in JSON: "
    '{"pass": true or false, "reason": "<one short sentence, quoting the line that decides it>"}'
)


def key(name: str) -> str:
    """A step or field name as it is compared: "Offer times" and "offer_times" are one."""
    return re.sub(r"[\s_-]+", "_", name.strip().lower())


def parse(line: str) -> dict:
    """The check a line states: { text, kind, name? }.

    `kind` is "reaches", "ends", "recorded" or "judged".
    """
    text = line.strip()
    bare = text.rstrip(".").strip()
    if match := _REACHES.fullmatch(bare):
        return {"text": text, "kind": "reaches", "name": match["name"]}
    if _ENDS.fullmatch(bare):
        return {"text": text, "kind": "ends"}
    if match := _RECORDED.fullmatch(bare):
        return {"text": text, "kind": "recorded", "name": match["name"]}
    return {"text": text, "kind": "judged"}


def decide(check: dict, call: dict) -> Optional[dict]:
    """A path check's result on `call`, { pass, detail }; None for a judged one."""
    path = call["path"]
    if check["kind"] == "reaches":
        if any(key(step["node"]) == key(check["name"]) for step in path):
            return {"pass": True, "detail": None}
        went = " → ".join(step["node"] for step in path) or "nowhere"
        return {"pass": False, "detail": f"Never got there: {went}."}
    if check["kind"] == "ends":
        ended = call["ended"]
        return {"pass": ended == "agent_ended", "detail": _ENDINGS.get(ended)}
    if check["kind"] == "recorded":
        for step in path:
            for field, value in step["collected"].items():
                if key(field) == key(check["name"]) and value not in (None, "", [], {}):
                    return {"pass": True, "detail": f"{field}: {value}"}
        return {"pass": False, "detail": "Never recorded."}
    return None


async def judge(client: AsyncOpenAI, model: str, check: str, transcript: list[dict]) -> dict:
    """A judged check's result: { pass, detail, tokens }."""
    lines = "\n".join(f"{line['role']}: {line['text']}" for line in transcript)
    response = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        max_completion_tokens=800,
        messages=[
            {"role": "system", "content": _JUDGE},
            {"role": "user", "content": f"Statement: {check}\n\nTranscript:\n{lines}"},
        ],
    )
    tokens = {
        "prompt": response.usage.prompt_tokens,
        "completion": response.usage.completion_tokens,
    }
    try:
        verdict = json.loads(response.choices[0].message.content or "")
        return {"pass": verdict["pass"] is True, "detail": str(verdict["reason"]), "tokens": tokens}
    except (ValueError, KeyError, TypeError):
        return {"pass": False, "detail": "The judge gave no verdict.", "tokens": tokens}
