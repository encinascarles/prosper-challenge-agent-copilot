#
# Stand-ins for the models a test run talks to, so simulated calls run here
# with no network: an LLM service that answers from a script, a caller that
# says scripted lines and a judge with a fixed verdict.
#
# The fake LLM is Pipecat's own OpenAILLMService with only the request to
# OpenAI replaced: everything after it (streaming, function calls, Flows'
# transitions, the frames a turn is made of) is the real code a call runs.
#

import json

from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from openai.types.completion_usage import CompletionUsage
from pipecat.services.openai.llm import OpenAILLMService

from simulate import Services


def say(text: str):
    """A response that says `text`."""
    return ("say", text)


def call(function: str, **arguments):
    """A response that calls the edge function `function` with `arguments`."""
    return ("call", function, arguments)


def _chunk(delta=None, usage=None) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="fake",
        created=0,
        model="fake",
        object="chat.completion.chunk",
        choices=[Choice(index=0, delta=delta, finish_reason=None)] if delta else [],
        usage=usage,
    )


class ScriptedLLM(OpenAILLMService):
    """Answers each request with the next response of its script."""

    def __init__(self, script: list):
        super().__init__(api_key="fake", settings=OpenAILLMService.Settings(model="fake"))
        self.script = list(script)
        self.requests = 0

    async def get_chat_completions(self, context):
        self.requests += 1
        response = self.script.pop(0)

        async def stream():
            if response[0] == "say":
                # In two pieces, as a stream would bring it.
                half = len(response[1]) // 2
                for piece in (response[1][:half], response[1][half:]):
                    yield _chunk(ChoiceDelta(content=piece))
            else:
                _, function, arguments = response
                tool_call = ChoiceDeltaToolCall(
                    index=0,
                    id=f"call_{self.requests}",
                    function=ChoiceDeltaToolCallFunction(
                        name=function, arguments=json.dumps(arguments)
                    ),
                )
                yield _chunk(ChoiceDelta(tool_calls=[tool_call]))
            usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            yield _chunk(usage=usage)

        return stream()


class ScriptedCaller:
    """Says its lines in order, then hangs up."""

    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        self.heard: list[list[dict]] = []  # the transcript, each time it was asked
        self.tokens = {"prompt": 1, "completion": 1}

    async def reply(self, transcript):
        self.heard.append(list(transcript))
        return self.lines.pop(0) if self.lines else None


# A booking through the sample agent, from greeting to goodbye.
BOOKING = [
    say("Hi, this is the clinic. Would you like to book, reschedule or cancel?"),
    call("choose_intent", intent="book"),
    say("Sure. May I have your full name and the reason for the visit?"),
    call("record_details", full_name="Maria Lopez", reason="check-up"),
    say("I can offer Tuesday at 10 AM or Thursday at 2 PM."),
    call("select_time", slot="Tuesday 10 AM"),
    say("You're booked, Maria, for Tuesday at 10 AM. Goodbye!"),
]
BOOKING_CALLER = ["I'd like to book.", "Maria Lopez, a check-up.", "Tuesday, please."]


class FakeServices(Services):
    """Every call gets the booking script; the judge passes whatever it is asked."""

    def __init__(self, script=None, lines=None, verdict=True):
        super().__init__()
        self.script = BOOKING if script is None else script
        self.lines = BOOKING_CALLER if lines is None else lines
        self.verdict = verdict
        self.judged: list[str] = []

    def llm(self, model):
        return ScriptedLLM(self.script)

    def caller(self, who):
        return ScriptedCaller(self.lines)

    async def judge(self, check, transcript):
        self.judged.append(check)
        reason = f"Judged on {len(transcript)} lines."
        return {"pass": self.verdict, "detail": reason, "tokens": {"prompt": 7, "completion": 3}}
