#
# Voice pipeline — Prosper Product Engineer Challenge
#
# The runnable voice agent: WebRTC transport + ElevenLabs STT/TTS + OpenAI LLM,
# driven by a Pipecat Flows node graph. This file is generic — it runs whatever
# agent the call was started for. Swapping the agent is a data change (save
# another agent JSON), not a code change.
#
#   /start { agent_id }  ->  store  ->  AgentBuilder  ->  Pipecat Flows graph  ->  FlowManager
#
# While the call runs, the browser is told each node the call enters, over the
# RTVI channel its client already has, so the editor can draw the call's path.
#
# Run:  python bot.py   then open http://localhost:7860/client (runs example_flow.json)
#

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner
from pipecat_flows import FlowManager

import api
import store
from agent_builder import NODE_ACTION, AgentBuilder

# Load .env next to this file, so the bot runs the same from the repo root or backend/.
load_dotenv(Path(__file__).parent / ".env", override=True)


transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


def report_nodes(flow_manager: FlowManager, worker: PipelineWorker) -> None:
    """Tell the browser each node the call enters, the start node included.

    The message is { type: "node", node, from, edge, collected }.
    """

    async def report(action: dict, flow_manager: FlowManager):
        # The builder's action minus what is Flows' business: its type and handler.
        message = {"type": "node"}
        message.update({key: action[key] for key in ("node", "from", "edge", "collected")})
        # A server message on the RTVI channel: the client hands it to the page
        # as it is, and no second connection is needed for it.
        await worker.queue_frame(RTVIServerMessageFrame(data=message))

    flow_manager.register_action(NODE_ACTION, report)


async def run_bot(
    transport: BaseTransport, runner_args: RunnerArguments, builder: AgentBuilder
) -> None:
    config = builder.config
    logger.info(f"Starting '{config.name}' with {len(config.nodes)} nodes")

    stt = ElevenLabsRealtimeSTTService(api_key=os.environ["ELEVENLABS_API_KEY"])
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice=config.voice_id),
    )
    llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model=config.model)

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
    )
    report_nodes(flow_manager, worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — starting flow at initial node")
        await flow_manager.initialize(builder.build_initial_node())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point invoked by the Pipecat dev runner (and Pipecat Cloud)."""
    try:
        builder = api.agent_for_call(runner_args.body)
    except api.CallError as error:
        # /start refuses these before any call. This is an offer sent straight
        # to /api/offer: hang up rather than leave the caller on a silent line.
        logger.error(f"Call not started: {error}")
        if connection := getattr(runner_args, "webrtc_connection", None):
            await connection.disconnect()
        return
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args, builder)


if __name__ == "__main__":
    from pipecat.runner.run import app, main

    # The builder API shares the runner's FastAPI server: one backend, one port,
    # and the browser reaches calls and agents through the same origin.
    store.init_db()
    api.mount(app)

    main()
