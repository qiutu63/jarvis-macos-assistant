from datetime import datetime

from app.permissions.policy import Risk
from app.tools.base import NoArguments, Tool
from app.tools.registry import ToolRegistry
from app.tools.system import system_tools
from app.tools.workspace import workspace_tools
from app.tools.browser import browser_tools
from app.tools.screen import screen_tools
from app.tools.accessibility import accessibility_tools
from pathlib import Path


async def current_time() -> dict:
    return {"time": datetime.now().astimezone().isoformat()}


def build_registry(workspace: Path | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("current_time", "查询本机当前时间及 UTC 时区偏移", NoArguments, current_time, Risk.SAFE))
    root = workspace or (Path.home() / "JARVIS_Workspace")
    for tool in [*workspace_tools(root), *system_tools(root)]:
        registry.register(tool)
    for tool in browser_tools():
        registry.register(tool)
    for tool in screen_tools():
        registry.register(tool)
    for tool in accessibility_tools():
        registry.register(tool)
    return registry
