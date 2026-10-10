import asyncio
import json
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from app.permissions.policy import Risk
from app.providers.base import ToolCall
from app.tools.registry import ToolRegistry


class Executor:
    def __init__(self, registry: ToolRegistry, timeout: float = 10,
                 confirm: Callable[[str, dict], Awaitable[bool]] | None = None):
        self.registry = registry
        self.timeout = timeout
        self.confirm = confirm

    async def execute(self, call: ToolCall) -> dict:
        try:
            tool = self.registry.get(call.name)
        except ValueError:
            return {"ok": False, "error": "unknown_tool", "detail": "工具未注册，请选择可用工具"}
        if tool.risk == Risk.BLOCKED:
            return {"ok": False, "error": "blocked"}
        try:
            args = tool.arguments.model_validate_json(call.arguments, strict=True).model_dump()
        except ValidationError:
            return {"ok": False, "error": "invalid_arguments", "detail": "参数与工具 schema 不符"}
        if tool.risk != Risk.SAFE:
            if self.confirm is None or not await self.confirm(tool.name, args):
                return {"ok": False, "error": "confirmation_denied"}
        try:
            result = await asyncio.wait_for(tool.handler(**args), timeout=tool.timeout or self.timeout)
            # Require a JSON result before appending it to a model transcript.
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 16000:
                return {"ok": False, "error": "result_too_large"}
            return {"ok": True, "result": result}
        except TimeoutError:
            return {"ok": False, "error": "tool_timeout", "detail": "工具超时；执行状态可能未知，不要盲目重复写入"}
        except Exception as error:
            return {"ok": False, "error": "tool_failed", "type": type(error).__name__,
                    "detail": "工具异常；原始异常未回传以避免泄露敏感数据"}
