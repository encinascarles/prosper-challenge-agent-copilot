#
# The one way Prosper AI talks to a model: a prompt, a JSON schema for the
# answer, a check of what comes back, and the check's error fed back when it
# fails.
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

# USD per million tokens: input, cached input, output. A model not listed is
# counted in tokens only.
PRICES = {
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}


class Failed(RuntimeError):
    """The model gave no answer that passed its check. The message says the last problem."""


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
            raw = self._complete(messages, name, schema)
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
        """One request; the answer's text. The tests replace this, and never reach OpenAI."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema, "strict": True},
            },
            max_completion_tokens=16000,
        )
        self.count(response.usage)
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise Failed(f"The model refused: {message.refusal}")
        return message.content or ""

    def count(self, usage) -> None:
        if usage is None:
            return
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        prompt_tokens, completion = usage.prompt_tokens, usage.completion_tokens
        fresh_in, cached_in, out = PRICES.get(self.model, (0, 0, 0))
        usd = ((prompt_tokens - cached) * fresh_in + cached * cached_in + completion * out) / 1e6
        with self._lock:
            self.usage["requests"] += 1
            self.usage["prompt"] += prompt_tokens
            self.usage["cached"] += cached
            self.usage["completion"] += completion
            self.usage["usd"] = round(self.usage["usd"] + usd, 4)
