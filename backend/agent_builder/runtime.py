#
# Running a compiled agent: the FlowManager over a pipeline, reporting where the
# call is, started at the agent's first node.
#
# Two pipelines run agents: the voice call (bot.py: audio in and out) and the
# text call the tests run (simulate/: text in and out). Everything between the
# LLM and the graph is the same for both, so it is written once, here: what is
# tested is what calls run. Each pipeline only says when to start (a voice call
# when the browser connects, a text call when its pipeline starts).
#

from typing import Awaitable, Callable, Optional

from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.services.llm_service import LLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat_flows import FlowManager

from .builder import AgentBuilder
from .schema import NODE_ACTION


def report_nodes(flow_manager: FlowManager, worker: PipelineWorker) -> None:
    """Send each node the call enters down the pipeline, the start node included.

    The message is { type: "node", node, from, edge, collected }. In a voice
    call it reaches the browser; in a text call, the processor that records it.
    """

    async def report(action: dict, flow_manager: FlowManager):
        # The builder's action minus what is Flows' business: its type and handler.
        message = {"type": "node"}
        message.update({key: action[key] for key in ("node", "from", "edge", "collected")})
        # A server message on the RTVI channel: the client hands it to the page
        # as it is, and no second connection is needed for it.
        await worker.queue_frame(RTVIServerMessageFrame(data=message))

    flow_manager.register_action(NODE_ACTION, report)


def start_flow(
    builder: AgentBuilder,
    llm: LLMService,
    context_aggregator: LLMContextAggregatorPair,
    worker: PipelineWorker,
    transport: Optional[BaseTransport] = None,
) -> Callable[[], Awaitable[None]]:
    """Put `builder`'s agent on the pipeline. Returns what starts it at its first node."""
    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
    )
    report_nodes(flow_manager, worker)

    async def start() -> None:
        await flow_manager.initialize(builder.build_initial_node())

    return start
