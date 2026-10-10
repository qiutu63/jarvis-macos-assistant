"""Native macOS Accessibility inspection and actions through the signed Swift helper."""
import asyncio
import json
import subprocess
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.permissions.policy import Risk
from app.tools.base import NoArguments, Tool
from app.voice import _build_helper


def _request(payload: dict) -> dict:
    executable = _build_helper()
    result = subprocess.run(
        [str(executable), "accessibility"],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip()[-800:] or "JARVIS Voice 辅助程序未能完成辅助功能请求。"
        return {"ok": False, "error": "accessibility_failed", "detail": detail}
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_accessibility_response"}
    return response if isinstance(response, dict) else {"ok": False, "error": "invalid_accessibility_response"}


class AccessibilityAction(StrEnum):
    press = "press"
    focus = "focus"
    set_text = "set_text"


class UIActionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    process_id: int = Field(gt=0)
    window_index: int = Field(default=0, ge=0, le=50)
    path: list[int] = Field(max_length=16)
    action: AccessibilityAction
    expected_role: str = Field(min_length=1, max_length=80)
    expected_identifier: str | None = Field(default=None, max_length=256)
    expected_title: str | None = Field(default=None, max_length=300)
    expected_description: str | None = Field(default=None, max_length=300)
    expected_bundle_id: str = Field(min_length=1, max_length=256)
    value: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_action_value(self):
        if self.action == AccessibilityAction.set_text and self.value is None:
            raise ValueError("set_text 必须提供 value")
        if self.action != AccessibilityAction.set_text and self.value is not None:
            raise ValueError("只有 set_text 可以提供 value")
        if not any((self.expected_identifier, self.expected_title, self.expected_description)):
            raise ValueError("必须提供刚检查到的控件标识或标题")
        return self


def accessibility_tools() -> list[Tool]:
    async def status():
        result = await asyncio.to_thread(_request, {"command": "status"})
        if not result.get("accessibility"):
            result["instructions"] = "请在系统设置 → 隐私与安全性 → 辅助功能中添加并启用项目内的 .build/JARVIS Voice.app；随后完全退出并重新打开 JARVIS。"
        return result

    async def inspect():
        return await asyncio.to_thread(_request, {"command": "inspect"})

    async def act(**arguments):
        payload = {"command": "act", **arguments}
        payload["action"] = arguments["action"].value
        payload["processID"] = payload.pop("process_id")
        payload["windowIndex"] = payload.pop("window_index")
        payload["expectedRole"] = payload.pop("expected_role")
        payload["expectedIdentifier"] = payload.pop("expected_identifier")
        payload["expectedTitle"] = payload.pop("expected_title")
        payload["expectedDescription"] = payload.pop("expected_description")
        payload["expectedBundleID"] = payload.pop("expected_bundle_id")
        return await asyncio.to_thread(_request, payload)

    return [
        Tool("check_accessibility_permission", "检查 JARVIS Voice 是否获准读取和操作 macOS 界面", NoArguments,
             status, Risk.SAFE),
        Tool("inspect_active_window", "读取当前前台应用的辅助功能窗口树；包括控件文字，可能包含私人信息", NoArguments,
             inspect, Risk.CONFIRM, timeout=30),
        Tool("operate_ui_element", "对刚检查到的控件执行 press、focus 或 set_text；操作前需重新校验控件身份", UIActionArguments,
             act, Risk.CONFIRM),
    ]
