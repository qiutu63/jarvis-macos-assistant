import json
from collections.abc import AsyncIterator

from app.providers.base import LLMProvider, Response, ToolCall


class MockProvider(LLMProvider):
    """Deterministic offline harness, not language understanding."""

    async def chat(self, messages: list[dict], tools: list[dict]) -> Response:
        last = messages[-1]
        if last["role"] == "tool":
            return Response(content="[离线演示] 工具观测结果：" + last["content"])
        text = last.get("content", "")
        if any(word in text for word in ("时间", "几点")) and any(t["function"]["name"] == "current_time" for t in tools):
            return Response(tool_calls=[ToolCall(id="offline_clock", name="current_time", arguments=json.dumps({}))])
        return Response(content="[离线演示，未调用真实 LLM] 收到：" + text + "。输入“当前时间”可验证工具循环；其他实际操作尚未启用。")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        yield (await self.chat(messages, [])).content
