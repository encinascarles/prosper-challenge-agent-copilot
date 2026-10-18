#
# Running an agent's tests: each test is called several times, all of a suite's
# calls at once, and each finished call is checked and handed on as it comes.
#
# A simulated call does not always go the same way, so one pass proves little:
# each test runs REPEATS times and is shown as "2/3", and passes only at 3/3.
# The calls are independent and spend their time waiting on the LLM, so they
# all run concurrently in one event loop, CONCURRENCY at a time to stay well
# under the API's rate limits.
#
# Who the agent talks to and who judges are `Services`, so the tests of this
# code run it with fakes and never reach OpenAI.
#

import asyncio
import os
from typing import Callable, Optional

from loguru import logger
from openai import AsyncOpenAI
from pipecat.services.llm_service import LLMService
from pipecat.services.openai.llm import OpenAILLMService

from agent_builder import AgentBuilder

from . import checks
from .caller import Caller
from .text_call import TextCall

REPEATS = 3
CONCURRENCY = 12
# The model that plays the caller and judges: ours, not the agent's. The agent
# runs on the model its JSON names, because that is what its calls run on.
DEFAULT_MODEL = "gpt-6.1-sol"
MODEL_ENV = "PROSPER_MODEL"


def prosper_model() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


class Services:
    """The models a test run talks to: the agent's LLM, the caller and the judge."""

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        # Made on first use, so nothing needs a key until a test actually runs.
        if self._client is None:
            self._client = AsyncOpenAI()
        return self._client

    def llm(self, model: str) -> LLMService:
        return OpenAILLMService(
            api_key=os.environ.get("OPENAI_API_KEY"),
            settings=OpenAILLMService.Settings(model=model),
        )

    def caller(self, who: str) -> Caller:
        return Caller(who, self.client, prosper_model())

    async def judge(self, check: str, transcript: list[dict]) -> dict:
        return await checks.judge(self.client, prosper_model(), check, transcript)


async def call_and_check(builder: AgentBuilder, test: dict, services: Services) -> dict:
    """One call of `test` against the agent, with every check decided. Never raises.

    Returns { path, transcript, ended, seconds, tokens, checks, passed }; a
    call that could not run has `ended` "error" and fails every check.
    """
    wanted = [checks.parse(line) for line in test["checks"]]
    judge_tokens = {"prompt": 0, "completion": 0}
    caller = services.caller(test["caller"])
    try:
        call = await TextCall(builder, services.llm(builder.config.model)).run(caller)
    except Exception as error:  # noqa: BLE001 - a broken call is a failed run, not a crash
        logger.exception(f"Test '{test['name']}' did not run")
        call = {"path": [], "transcript": [], "ended": "error", "tokens": {}, "seconds": 0}
        failed = {"pass": False, "detail": f"The call did not run: {error}"}
        results = [{"text": c["text"], "kind": c["kind"], **failed} for c in wanted]
    else:
        results = []
        for check in wanted:
            result = checks.decide(check, call)
            if result is None:
                try:
                    result = await services.judge(check["text"], call["transcript"])
                    for k, v in result.pop("tokens", {}).items():
                        judge_tokens[k] += v
                except Exception as error:  # noqa: BLE001
                    result = {"pass": False, "detail": f"Could not be judged: {error}"}
            results.append({"text": check["text"], "kind": check["kind"], **result})
    return {
        **call,
        "tokens": {
            "agent": call["tokens"],
            "caller": getattr(caller, "tokens", {}),
            "judge": judge_tokens,
        },
        "checks": results,
        "passed": all(result["pass"] for result in results),
    }


async def run_suite(
    config: dict,
    rules: list,
    tests: list,
    on_result: Callable[[dict, dict], None],
    services: Optional[Services] = None,
    repeats: int = REPEATS,
    concurrency: int = CONCURRENCY,
) -> None:
    """Call every test `repeats` times against the agent.

    Each call's result is handed to `on_result(test, result)` as it finishes.
    """
    services = services or Services()
    builder = AgentBuilder.from_dict(config, rules)
    gate = asyncio.Semaphore(concurrency)

    async def one(test: dict):
        async with gate:
            result = await call_and_check(builder, test, services)
        on_result(test, result)

    await asyncio.gather(*(one(test) for test in tests for _ in range(repeats)))
