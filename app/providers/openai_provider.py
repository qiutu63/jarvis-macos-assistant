import asyncio
import json
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx

from app.providers.base import LLMProvider, ProviderError, Response, ToolCall


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible Chat Completions transport, shared by adapters."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 30,
                 transport: httpx.AsyncBaseTransport | None = None):
        url = urlsplit(base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("模型 Base URL 必须是无凭据、无查询参数的 HTTPS 地址")
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/",
                                       headers={"Authorization": f"Bearer {api_key}"},
                                       timeout=timeout, transport=transport, follow_redirects=False)

    async def chat(self, messages: list[dict], tools: list[dict]) -> Response:
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        # Retry transient provider failures only; never re-execute tools here.
        for attempt in range(3):
            try:
                response = await self.client.post("chat/completions", json=payload)
                if (response.status_code == 429 or response.status_code >= 500) and attempt < 2:
                    await asyncio.sleep(0.2 * (2 ** attempt))
                    continue
                if not response.is_success:
                    raise ProviderError(f"模型请求失败 HTTP {response.status_code}；请检查凭据、模型权限、地址或额度")
                choice = response.json()["choices"][0]
                if choice.get("finish_reason") in ("length", "content_filter"):
                    raise ProviderError("模型回复被截断或过滤；请缩短输入后重试")
                message = choice["message"]
                calls = [ToolCall(id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"])
                         for c in message.get("tool_calls", [])]
                if len({c.id for c in calls}) != len(calls):
                    raise ValueError("duplicate tool IDs")
                content = message.get("content") or ""
                if not content and not calls:
                    raise ProviderError("模型返回空响应")
                return Response(content=content, tool_calls=calls)
            except httpx.RequestError:
                if attempt == 2:
                    raise ProviderError("模型连接失败或超时；请检查网络与 Base URL") from None
                await asyncio.sleep(0.2 * (2 ** attempt))
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                raise ProviderError("模型响应格式不兼容 Chat Completions") from None
        raise ProviderError("模型重试次数耗尽")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        try:
            async with self.client.stream("POST", "chat/completions", json={
                "model": self.model, "messages": messages, "stream": True
            }) as response:
                if not response.is_success:
                    raise ProviderError(f"模型流请求失败 HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    chunk = json.loads(data)
                    for choice in chunk.get("choices", []):
                        if choice.get("finish_reason") in ("length", "content_filter"):
                            raise ProviderError("模型流输出被截断或过滤")
                        text = choice.get("delta", {}).get("content")
                        if text:
                            yield text
                raise ProviderError("模型流意外中断")
        except httpx.RequestError:
            raise ProviderError("模型流连接失败或超时") from None
        except (ValueError, TypeError, AttributeError):
            raise ProviderError("模型流响应格式错误") from None

    async def close(self) -> None:
        await self.client.aclose()
