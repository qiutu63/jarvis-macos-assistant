from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class Response(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)

    def message(self) -> dict:
        result: dict[str, Any] = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return result


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict], tools: list[dict]) -> Response:
        ...

    @abstractmethod
    def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Text-only streaming; tool execution uses structured chat responses."""
        ...

    async def close(self) -> None:
        pass
