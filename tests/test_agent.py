import asyncio
import json

import pytest

from app.agent.core import Agent
from app.agent.executor import Executor
from app.agent.state import State
from app.events.bus import EventBus
from app.permissions.policy import Risk
from app.providers.base import Response, ToolCall
from app.providers.mock_provider import MockProvider
from app.tools.base import NoArguments, Tool
from app.tools.builtin import build_registry


async def test_complete_tool_loop_and_events():
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    agent = Agent(MockProvider(), build_registry(), bus=bus)
    result = await agent.run("当前时间")
    assert '"ok": true' in result
    assert agent.state == State.COMPLETED
    assert [e.state for e in events] == ["Thinking", "Planning", "Executing", "Observing", "Planning", "Completed"]
    assert [m["role"] for m in agent.history[0]] == ["user", "assistant", "tool", "assistant"]


async def test_history_bounded_and_reset():
    agent = Agent(MockProvider(), build_registry(), history_turns=2)
    for i in range(5):
        await agent.run(str(i))
    assert len(agent.history) == 2
    agent.reset()
    assert not agent.history
    assert agent.state == State.WAITING


@pytest.mark.parametrize("risk,approve,expected", [
    (Risk.BLOCKED, True, False), (Risk.CONFIRM, False, False), (Risk.CONFIRM, True, True),
    (Risk.SAFE, False, True)])
async def test_permission_enforcement(risk, approve, expected):
    ran = []
    async def handler():
        ran.append(True)
        return "ok"
    async def confirm(name, args):
        return approve
    registry = build_registry()
    registry.register(Tool("test", "test", NoArguments, handler, risk))
    result = await Executor(registry, confirm=confirm).execute(ToolCall(id="a", name="test", arguments="{}"))
    assert result["ok"] == expected
    assert bool(ran) == expected


async def test_fail_closed_without_confirm_and_bad_args():
    registry = build_registry()
    registry.register(Tool("confirm", "confirm", NoArguments, registry.get("current_time").handler))
    executor = Executor(registry)
    assert (await executor.execute(ToolCall(id="a", name="confirm", arguments="{}")))["error"] == "confirmation_denied"
    for args in ('{"extra":true}', "not json", "[]"):
        assert (await executor.execute(ToolCall(id="a", name="current_time", arguments=args)))["error"] == "invalid_arguments"


async def test_error_replanning():
    class Recover(MockProvider):
        async def chat(self, messages, tools):
            if messages[-1]["role"] == "user":
                return Response(tool_calls=[ToolCall(id="bad", name="missing", arguments="{}")])
            result = json.loads(messages[-1]["content"])
            if not result["ok"]:
                return Response(tool_calls=[ToolCall(id="good", name="current_time", arguments="{}")])
            return Response(content="已恢复")
    agent = Agent(Recover(), build_registry())
    assert await agent.run("test") == "已恢复"


async def test_step_limit_and_no_partial_history():
    class Forever(MockProvider):
        async def chat(self, messages, tools):
            return Response(tool_calls=[ToolCall(id="loop", name="current_time", arguments="{}")])
    agent = Agent(Forever(), build_registry(), max_steps=2)
    with pytest.raises(RuntimeError, match="步数上限"):
        await agent.run("test")
    assert not agent.history
    assert agent.state == State.ERROR


async def test_timeout():
    async def slow():
        await asyncio.sleep(1)
    registry = build_registry()
    registry.register(Tool("slow", "slow", NoArguments, slow, Risk.SAFE))
    result = await Executor(registry, timeout=0.01).execute(ToolCall(id="s", name="slow", arguments="{}"))
    assert result["error"] == "tool_timeout"


async def test_listener_failure_does_not_break_agent():
    bus = EventBus()
    def broken(event):
        raise RuntimeError("listener")
    bus.subscribe(broken)
    agent = Agent(MockProvider(), build_registry(), bus=bus)
    assert await agent.run("你好")
