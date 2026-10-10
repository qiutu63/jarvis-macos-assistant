import httpx
import pytest

from app.config.settings import load_settings
from app.providers.base import ProviderError
from app.providers.openai_provider import OpenAIProvider
from app.tools.builtin import build_registry


def test_registry_duplicate_and_schema():
    registry = build_registry()
    assert registry.schemas()[0]["function"]["name"] == "current_time"
    with pytest.raises(ValueError):
        registry.register(registry.get("current_time"))
    with pytest.raises(ValueError):
        registry.get("execute_terminal")


def test_config_missing_key(tmp_path, monkeypatch):
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_settings(tmp_path, provider="openai")


async def test_provider_serialization():
    def handle(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]})
    provider = OpenAIProvider("test-secret", "https://example.test/v1", "test", transport=httpx.MockTransport(handle))
    try:
        assert (await provider.chat([{"role": "user", "content": "你好"}], [])).content == "你好"
    finally:
        await provider.close()


async def test_http_error_is_redacted():
    provider = OpenAIProvider("secret", "https://example.test/v1", "test", transport=httpx.MockTransport(
        lambda r: httpx.Response(401, text="secret response body")))
    try:
        with pytest.raises(ProviderError, match="401") as error:
            await provider.chat([], [])
        assert "secret" not in str(error.value)
    finally:
        await provider.close()


async def test_stream():
    body = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n'
    provider = OpenAIProvider("secret", "https://example.test/v1", "test", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=body)))
    try:
        assert [part async for part in provider.stream([])] == ["你好"]
    finally:
        await provider.close()


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": None}]},
                                 {"choices": [{"message": {"content": ""}}]}])
async def test_bad_responses(body):
    provider = OpenAIProvider("secret", "https://example.test/v1", "test", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=body)))
    try:
        with pytest.raises(ProviderError):
            await provider.chat([], [])
    finally:
        await provider.close()


async def test_transient_retry_and_tool_calls():
    attempts = []
    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "clock", "function": {"name": "current_time", "arguments": "{}"}}
        ]}}]})
    provider = OpenAIProvider("secret", "https://example.test/v1", "test", transport=httpx.MockTransport(handle))
    try:
        result = await provider.chat([], build_registry().schemas())
        assert result.tool_calls[0].name == "current_time"
        assert len(attempts) == 2
        assert result.message()["tool_calls"][0]["id"] == "clock"
    finally:
        await provider.close()


def test_insecure_url_rejected():
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAIProvider("secret", "http://example.test/v1", "test")
