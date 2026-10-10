from app.tools.base import Tool
from app.permissions.policy import Risk


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ValueError("未知工具")
        return self._tools[name]

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values() if t.risk != Risk.BLOCKED]

    def describe(self) -> list[str]:
        return [f"{t.name} [{t.risk}] — {t.description}" for t in self._tools.values()]
