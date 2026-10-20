#
# The one way Prosper AI talks to a model: a prompt, a JSON schema for the
# answer, a check of what comes back, and the check's error fed back when it
# fails.
#
# Ask Prosper AI also talks with tools (`turn`): one step of a conversation in
# which the model may call a function instead of answering.
#
# Plain OpenAI SDK, no agent framework: each artifact (an agent, its rules,
# its tests, its questions) is one request with Structured Outputs, so the
# answer always parses into the shape asked for. What a schema cannot say
# (that an edge's target is a step that exists, that a quote is really in the
# guidelines) is checked in code. A refused answer is sent back with the
# sentence that says what is wrong, the same sentence a save would get, and the
# model answers again: twice at most, then the job says it could not.
#
# Every request's tokens are counted and priced, so a setup can say what it
# cost. The model is ours, not the agent's: PROSPER_MODEL, as for the
# simulated caller and the judge.
#

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from loguru import logger
from openai import OpenAI

from simulate.suite import prosper_model

PROMPTS = Path(__file__).parent / "prompts"
ATTEMPTS = 3
# Low reasoning effort: each artifact is a well-specified piece, and at the
# default the model can think for minutes and spend the whole budget before it
# writes a word. MAX_TOKENS bounds what one request can cost (USD 0.06 on
# PROSPER_MODEL): a whole agent is about 2,000 tokens, and a request that runs
# past it has got stuck, which happens now and then; it is tried once more.
EFFORT = "low"
MAX_TOKENS = 6000
# A review or a change writes the whole agent back with its verdicts, tests and
# rules: a real one ran past 6,000 tokens of plain answer, twice.
LONGER = {"review": 12000, "change": 12000}

# USD per million tokens: input, cached input, output. A model not listed is
# counted in tokens only.
PRICES = {
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}


def price(model: str, prompt: int, completion: int, cached: int = 0) -> float:
    """What `model` charges for these tokens, in USD; 0 for a model not listed."""
    fresh_in, cached_in, out = PRICES.get(model, (0, 0, 0))
    return ((prompt - cached) * fresh_in + cached * cached_in + completion * out) / 1e6


class Failed(RuntimeError):
    """The model gave no answer that passed its check. The message says the last problem."""


class CutOff(Failed):
    """The answer ran past MAX_TOKENS before it was finished."""


def prompt(name: str) -> str:
    """The prompt `name`, from prompts/<name>.md: plain files, so a reviewer can read them."""
    return (PROMPTS / f"{name}.md").read_text()


class LLM:
    """Structured requests to Prosper AI's model, with retries and a running count of usage."""

    def __init__(self, client: Optional[OpenAI] = None, model: Optional[str] = None):
        self._client = client
        self.model = model or prosper_model()
        self.usage = {"requests": 0, "prompt": 0, "cached": 0, "completion": 0, "usd": 0.0}
        # Rules, tests and questions are asked for at once, from threads.
        self._lock = threading.Lock()

    @property
    def client(self) -> OpenAI:
        # Made on first use, so nothing needs a key until a request is made.
        if self._client is None:
            self._client = OpenAI()
        return self._client

    def ask(
        self,
        name: str,
        content: str,
        schema: dict,
        check: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """The answer to prompt `name` about `content`, shaped by `schema` and passing `check`.

        `check` raises ValueError with what is wrong; that sentence goes back
        to the model, which answers again. Raises Failed after ATTEMPTS.
        """
        messages = [
            {"role": "system", "content": prompt(name)},
            {"role": "user", "content": content},
        ]
        problem = ""
        for attempt in range(1, ATTEMPTS + 1):
            started = time.monotonic()
            try:
                raw = self._complete(messages, name, schema)
            except CutOff as error:
                # Not the model's fault to correct: ask the same again, once.
                problem = str(error)
                logger.warning(f"Prosper AI · {name} · attempt {attempt} · {problem}")
                if attempt >= 2:
                    raise
                continue
            took = time.monotonic() - started
            logger.info(f"Prosper AI · {name} · attempt {attempt} · {took:.1f}s")
            try:
                answer = json.loads(raw)
                if check is not None:
                    check(answer)
                return answer
            except ValueError as error:
                problem = str(error)
                logger.warning(f"Prosper AI · {name} · refused: {problem}")
                messages += [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"That was refused: {problem}\n"
                        "Fix it and answer again with the whole JSON.",
                    },
                ]
        raise Failed(problem)

    def _complete(self, messages: list, name: str, schema: dict) -> str:
        """One request; the answer's text. The tests replace this, and never reach OpenAI.

        Through the Responses API: on Chat Completions, at the same low effort,
        about one request in two thought to its token limit and wrote nothing;
        the same request here thinks a few hundred tokens and answers.
        """
        response = self.client.responses.create(
            model=self.model,
            instructions=messages[0]["content"],
            input=messages[1:],
            text={
                "format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}
            },
            reasoning={"effort": EFFORT},
            max_output_tokens=LONGER.get(name, MAX_TOKENS),
        )
        self.count(response.usage)
        for item in response.output:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", "") == "refusal":
                    raise Failed(f"The model refused: {part.refusal}")
        if response.status == "incomplete":
            details = getattr(response.usage, "output_tokens_details", None)
            thought = getattr(details, "reasoning_tokens", 0) or 0
            text = response.output_text or ""
            # Its end says why: a real answer that needed more room, or one
            # that went round in circles (the same words, or blank space).
            logger.warning(
                f"Prosper AI · {name} · cut off: {thought} tokens thinking, "
                f"wrote {len(text)} characters: {text[:120]!r} … {text[-300:]!r}"
            )
            raise CutOff("The model ran out of room before it finished its answer.")
        return response.output_text or ""

    def turn(
        self, name: str, items: list, tools: list, schema: dict, use_tools: bool = True
    ) -> dict:
        """One step of a conversation where the model may call a tool: { output, call, text }.

        `items` is the conversation so far, the way the Responses API takes
        it; `output` is what this step adds to it. `call` is the one function
        the model calls ({ call_id, name, arguments }), or None when it
        answered: then `text` is the JSON `schema` asks for. Without
        `use_tools`, it has to answer.

        Kept on our side, the whole conversation, and sent again each step:
        the organization's key keeps nothing at OpenAI (zero data retention),
        so a response cannot be continued by its id. The model's reasoning
        travels encrypted with it, so it picks up where it left off.
        """
        started = time.monotonic()
        step = self._turn(name, items, tools, schema, use_tools)
        took = time.monotonic() - started
        did = f"calls {step['call']['name']}" if step["call"] else "answers"
        logger.info(f"Prosper AI · {name} · {did} · {took:.1f}s")
        return step

    def _turn(self, name: str, items: list, tools: list, schema: dict, use_tools: bool) -> dict:
        """One request of a conversation with tools. The tests replace this: never OpenAI."""
        response = self.client.responses.create(
            model=self.model,
            instructions=prompt(name),
            input=items,
            tools=tools,
            tool_choice="auto" if use_tools else "none",
            # One at a time: a call that acts waits for the person, and
            # whatever came with it would wait too.
            parallel_tool_calls=False,
            text={
                "format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}
            },
            reasoning={"effort": EFFORT},
            max_output_tokens=MAX_TOKENS,
            store=False,
            include=["reasoning.encrypted_content"],
        )
        self.count(response.usage)
        if response.status == "incomplete":
            raise CutOff("The model ran out of room before it finished its answer.")
        output = [item.model_dump(exclude_none=True) for item in response.output]
        call = next((item for item in output if item["type"] == "function_call"), None)
        if call is not None:
            call = {key: call[key] for key in ("call_id", "name", "arguments")}
        return {"output": output, "call": call, "text": response.output_text or ""}

    def add_cost(self, usd: float) -> None:
        """Count what something else this work paid for cost: the simulated calls it made."""
        with self._lock:
            self.usage["usd"] = round(self.usage["usd"] + usd, 4)

    def count(self, usage) -> None:
        if usage is None:
            return
        # Responses names them input and output; Chat Completions, prompt and completion.
        details = getattr(usage, "input_tokens_details", None) or getattr(
            usage, "prompt_tokens_details", None
        )
        cached = getattr(details, "cached_tokens", 0) or 0
        prompt_tokens = getattr(usage, "input_tokens", None) or usage.prompt_tokens
        completion = getattr(usage, "output_tokens", None) or usage.completion_tokens
        usd = price(self.model, prompt_tokens, completion, cached)
        with self._lock:
            self.usage["requests"] += 1
            self.usage["prompt"] += prompt_tokens
            self.usage["cached"] += cached
            self.usage["completion"] += completion
            self.usage["usd"] = round(self.usage["usd"] + usd, 4)
