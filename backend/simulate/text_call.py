#
# A call in text: the agent as calls run it (AgentBuilder, Pipecat Flows'
# FlowManager, the LLM service) in a Pipecat pipeline with no audio, talked to
# by a simulated caller.
#
#   caller line -> LLMMessagesAppendFrame -> user aggregator -> LLM -> TextOutput
#               -> assistant aggregator
#
# TextOutput stands where TTS and the transport's output stand in a voice call:
# it collects what the agent says, says the text of a TTSSpeakFrame (`tts_say`,
# what end_conversation says), records the node messages the call reports, and
# after each spoken reply sends the BotStarted/Stopped speaking frames the
# transport would. Flows only needs those for post-actions it defers until the
# agent has spoken.
#
# The agent's turn ends at the LLMFullResponseEndFrame of a response that
# called no function. A response that called one makes Flows move to the next
# node and run the LLM again, so its turn goes on, through as many silent
# transitions as it takes. FunctionCallsStartedFrame comes before that
# response's end frame, which is what makes the rule reliable; the tests pin it.
# It is a system frame, so it can also overtake the response's start frame:
# the functions are counted from one end frame to the next, not from the start.
#
# The path is the same messages a voice call sends the browser
# (agent_builder/runtime.py), so a test and a call trace a path the same way.
#

import asyncio
import time
from typing import Optional, Protocol

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallsStartedFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    LLMTextFrame,
    MetricsFrame,
    TextFrame,
    TTSSpeakFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.services.llm_service import LLMService
from pipecat.workers.runner import WorkerRunner

from agent_builder import AgentBuilder
from agent_builder.runtime import start_flow

MAX_TURNS = 16  # caller lines before a call that goes nowhere is cut
TURN_TIMEOUT = 60  # seconds for one agent turn before the call is called stuck
END_TIMEOUT = 10  # seconds for the pipeline to finish once the end step has spoken


class Caller(Protocol):
    """Whoever talks to the agent: given the call so far, the next line, or None to hang up."""

    async def reply(self, transcript: list[dict]) -> Optional[str]: ...


class TextOutput(FrameProcessor):
    """Where TTS and the transport's output sit in a voice call: records what the call does."""

    def __init__(self, call: "TextCall"):
        super().__init__()
        self._call = call
        self._text: list[str] = []
        self._functions = 0

    async def _spoke(self, text: str):
        self._call.said(text)
        await self.push_frame(BotStartedSpeakingFrame())
        await self.push_frame(BotStoppedSpeakingFrame())

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._text = []
        elif isinstance(frame, LLMTextFrame):
            self._text.append(frame.text)
        elif isinstance(frame, FunctionCallsStartedFrame):
            self._functions += len(frame.function_calls)
        elif isinstance(frame, MetricsFrame):
            for data in frame.data:
                if isinstance(data, LLMUsageMetricsData):
                    self._call.used(data.value)
        elif isinstance(frame, RTVIServerMessageFrame):
            self._call.entered(frame.data)
        elif isinstance(frame, TTSSpeakFrame):
            # What a TTS does with it: say it, and hand the text on to the
            # assistant aggregator so it is in the context.
            await self.push_frame(TextFrame(frame.text), direction)
            await self._spoke(frame.text)
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            await self.push_frame(frame, direction)
            text = "".join(self._text).strip()
            if text:
                await self._spoke(text)
            if not self._functions:
                self._call.turn_done.set()
            self._functions = 0
            return
        await self.push_frame(frame, direction)


class TextCall:
    """One simulated call against a compiled agent."""

    def __init__(self, builder: AgentBuilder, llm: LLMService):
        self.builder = builder
        self.llm = llm
        self.transcript: list[dict] = []  # { role: "agent" | "caller", text, node }
        self.path: list[dict] = []  # { node, from, edge, collected }, as a voice call reports it
        self.tokens = {"prompt": 0, "completion": 0}
        self.turn_done = asyncio.Event()
        self._end_nodes = {node.name for node in builder.config.nodes if node.end}

    # What TextOutput saw.
    def said(self, text: str):
        self.transcript.append({"role": "agent", "text": text, "node": self.node})

    def used(self, usage):
        self.tokens["prompt"] += usage.prompt_tokens
        self.tokens["completion"] += usage.completion_tokens

    def entered(self, message):
        if isinstance(message, dict) and message.get("type") == "node":
            self.path.append({key: message[key] for key in ("node", "from", "edge", "collected")})

    @property
    def node(self) -> Optional[str]:
        return self.path[-1]["node"] if self.path else None

    async def run(self, caller: Caller, max_turns: int = MAX_TURNS) -> dict:
        """Run the call to its end. Returns its path, transcript, how it ended, tokens and seconds.

        `ended` is "agent_ended", "caller_hung_up", "turn_cap" (still going after
        `max_turns` caller lines), "stuck" (the agent did not finish a turn in
        time) or "end_not_reached" (the end step spoke but the call went on).
        """
        started = time.monotonic()
        aggregator = LLMContextAggregatorPair(LLMContext())
        pipeline = Pipeline([aggregator.user(), self.llm, TextOutput(self), aggregator.assistant()])
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
            idle_timeout_secs=None,
        )
        start_agent = start_flow(self.builder, self.llm, aggregator, worker)
        finished = asyncio.Event()

        @worker.event_handler("on_pipeline_started")
        async def on_started(worker, frame):
            # Where a voice call starts when the browser connects.
            await start_agent()

        @worker.event_handler("on_pipeline_finished")
        async def on_finished(worker, frame):
            finished.set()
            self.turn_done.set()  # a turn being waited for will not come

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())

        ended, turns = None, 0
        try:
            while ended is None:
                try:
                    await asyncio.wait_for(self.turn_done.wait(), TURN_TIMEOUT)
                except asyncio.TimeoutError:
                    ended = "stuck"
                    break
                self.turn_done.clear()
                if self.node in self._end_nodes:
                    # The end step spoke: Flows ends the call. Wait for it rather
                    # than race the caller's next line.
                    try:
                        await asyncio.wait_for(finished.wait(), END_TIMEOUT)
                        ended = "agent_ended"
                    except asyncio.TimeoutError:
                        ended = "end_not_reached"
                elif finished.is_set():
                    ended = "agent_ended"
                elif turns >= max_turns:
                    ended = "turn_cap"
                else:
                    line = await caller.reply(self.transcript)
                    turns += 1
                    if not line:
                        ended = "caller_hung_up"
                        break
                    self.transcript.append({"role": "caller", "text": line, "node": self.node})
                    await worker.queue_frame(
                        LLMMessagesAppendFrame(
                            messages=[{"role": "user", "content": line}], run_llm=True
                        )
                    )
        finally:
            if not finished.is_set():
                await worker.cancel()
            await running

        return {
            "path": self.path,
            "transcript": self.transcript,
            "ended": ended,
            "tokens": self.tokens,
            "seconds": round(time.monotonic() - started, 1),
        }
