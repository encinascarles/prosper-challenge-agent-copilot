#
# Following a call, with no call: no WebRTC, no OpenAI and no ElevenLabs.
#
# The browser is told each node the call enters and what brought it there, which
# is what the editor draws the call's path from. These go through a real Flows
# FlowManager over a worker that only records frames, so it is Flows that runs
# the transition, as in a call.
#

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from pipecat.frames.frames import LLMSetToolsFrame
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat_flows import FlowManager

import bot
from agent_builder import AgentBuilder


class RecordingWorker:
    """What FlowManager needs of a PipelineWorker: somewhere to queue frames."""

    def __init__(self):
        self.frames = []

    async def queue_frame(self, frame):
        self.frames.append(frame)

    async def queue_frames(self, frames):
        self.frames.extend(frames)

    def set_reached_downstream_filter(self, types):
        pass

    def event_handler(self, name):
        return lambda handler: handler

    def node_messages(self) -> list[dict]:
        return [f.data for f in self.frames if isinstance(f, RTVIServerMessageFrame)]

    def tool(self, name):
        """The function the LLM would call for the edge `name` of the current node."""
        tools = [f for f in self.frames if isinstance(f, LLMSetToolsFrame)][-1].tools
        return next(t.handler for t in tools.standard_tools if t.name == name)


async def _call(worker: RecordingWorker, function: str, arguments: dict) -> None:
    """Have the model call an edge function, the way Pipecat's LLM service does."""
    done = {}

    async def result_callback(result, properties=None):
        done["properties"] = properties

    params = SimpleNamespace(arguments=arguments, result_callback=result_callback)
    await worker.tool(function)(params)
    # Pipecat calls this once the result is in the context; Flows moves on then.
    await done["properties"].on_context_updated()


def _flow(worker: RecordingWorker, report: bool = True) -> FlowManager:
    aggregator = MagicMock()
    aggregator.assistant.return_value.has_function_calls_in_progress = False
    flow_manager = FlowManager(llm=MagicMock(), context_aggregator=aggregator, worker=worker)
    if report:
        bot.report_nodes(flow_manager, worker)
    return flow_manager


def test_the_browser_is_told_the_start_node_when_the_call_starts(agent):
    worker = RecordingWorker()

    asyncio.run(_flow(worker).initialize(AgentBuilder.from_dict(agent).build_initial_node()))

    assert worker.node_messages() == [
        {"type": "node", "node": "greeting", "from": None, "edge": None, "collected": {}}
    ]


def test_the_browser_is_told_each_node_change_with_what_caused_it(agent):
    worker = RecordingWorker()

    async def call():
        await _flow(worker).initialize(AgentBuilder.from_dict(agent).build_initial_node())
        await _call(worker, "choose_intent", {"intent": "book"})

    asyncio.run(call())

    assert worker.node_messages()[1:] == [
        {
            "type": "node",
            "node": "collect_details",
            "from": "greeting",
            "edge": "choose_intent",
            "collected": {"intent": "book"},
        }
    ]


def test_the_node_is_reported_before_the_nodes_own_pre_actions(agent):
    agent["nodes"][0]["pre_actions"] = [{"type": "tts_say", "text": "One moment."}]

    node = AgentBuilder.from_dict(agent).build_initial_node()

    assert [action["type"] for action in node["pre_actions"]] == ["node_entered", "tts_say"]


def test_the_graph_runs_without_a_reporter(agent):
    # A runner that is not the voice bot (a text simulation) need not register one.
    worker = RecordingWorker()

    async def call():
        flow_manager = _flow(worker, report=False)
        await flow_manager.initialize(AgentBuilder.from_dict(agent).build_initial_node())
        await _call(worker, "choose_intent", {"intent": "book"})
        return flow_manager.current_node

    assert asyncio.run(call()) == "collect_details"
    assert worker.node_messages() == []
