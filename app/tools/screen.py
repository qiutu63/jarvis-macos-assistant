"""Permission-gated macOS screen OCR and tightly scoped input tools."""
import os
import asyncio
import subprocess
import tempfile
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.permissions.policy import Risk
from app.tools.base import NoArguments, Tool


def _frameworks():
    try:
        import Foundation
        import Quartz
        import Vision
    except ImportError as exc:
        raise RuntimeError("macOS 屏幕工具依赖未安装；请安装项目的 macos 可选依赖") from exc
    return Foundation, Quartz, Vision


def _permissions() -> dict:
    try:
        _, quartz, _ = _frameworks()
    except RuntimeError:
        return {"screen_capture": False, "input_control": False,
                "install_required": True, "instructions": "先安装项目的 macos 可选依赖。"}
    guidance = ("在系统设置 → 隐私与安全性 → 屏幕录制 / 辅助功能中，"
                "授权给当前启动 JARVIS 的应用：桌面版选择 JARVIS Desktop Pet；"
                "命令行版选择 Terminal。授权后完全退出并重新打开 JARVIS。")
    return {
        "screen_capture": bool(quartz.CGPreflightScreenCaptureAccess()),
        "input_control": bool(quartz.CGPreflightPostEventAccess()),
        "install_required": False,
        "instructions": guidance,
    }


def _permission_error(which: str) -> dict:
    label = "屏幕录制" if which == "screen_capture" else "辅助功能（控制电脑）"
    return {"ok": False, "error": "permission_required", "detail": f"请在系统设置 → 隐私与安全性中，为当前启动 JARVIS 的应用（桌面版为 JARVIS Desktop Pet，命令行版为 Terminal）授予{label}权限，然后完全退出并重新打开 JARVIS。"}


def permission_status() -> dict:
    return _permissions()


def capture_screen_text() -> dict:
    status = _permissions()
    if status["install_required"]:
        return {"ok": False, "error": "dependency_missing", "detail": status["instructions"]}
    if not status["screen_capture"]:
        return _permission_error("screen_capture")
    foundation, quartz, vision = _frameworks()
    capture = "/usr/sbin/screencapture"
    if not os.path.isfile(capture):
        return {"ok": False, "error": "unsupported_platform", "detail": "macOS screencapture 命令不可用。"}
    fd, image_path = tempfile.mkstemp(prefix="jarvis-screen-", suffix=".png")
    os.close(fd)
    stage = "capture"
    try:
        os.unlink(image_path)
        result = subprocess.run([capture, "-x", "-m", "-t", "png", image_path],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6, check=False)
        if result.returncode != 0 or not os.path.isfile(image_path):
            message = result.stderr.decode("utf-8", errors="replace").strip()[:400]
            return {"ok": False, "error": "capture_failed", "returncode": result.returncode,
                    "detail": message or "系统截图命令没有生成图像。"}
        stage = "resize_screenshot"
        # Preserve fine text strokes for OCR while avoiding needless work on
        # very high-resolution displays.
        resized = subprocess.run(["/usr/bin/sips", "-Z", "2800", image_path],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
        if resized.returncode != 0:
            message = resized.stderr.decode("utf-8", errors="replace").strip()[:300]
            return {"ok": False, "error": "image_resize_failed",
                    "detail": message or "无法缩小屏幕截图供 OCR 处理。"}
        stage = "create_vision_request"
        request = vision.VNRecognizeTextRequest.alloc().init()
        stage = "configure_vision_request"
        request.setRecognitionLevel_(vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["zh-Hans", "en-US"])
        request.setUsesLanguageCorrection_(True)
        stage = "create_vision_handler"
        url = foundation.NSURL.fileURLWithPath_(image_path)
        # On macOS 27 with PyObjC 12, bridging an empty Python dict as the
        # Vision options NSDictionary can raise NSInvalidArgumentException.
        # `None` correctly represents an empty options dictionary here.
        handler = vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        stage = "perform_vision_request"
        outcome = handler.performRequests_error_([request], None)
        stage = "read_vision_result"
        success = outcome[0] if isinstance(outcome, tuple) else outcome
        if not success:
            return {"ok": False, "error": "ocr_failed", "detail": "macOS Vision 未能处理截图。"}
        stage = "extract_coordinates"
        bounds = quartz.CGDisplayBounds(quartz.CGMainDisplayID())
        items = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            box = observation.boundingBox()
            center_x = bounds.origin.x + (box.origin.x + box.size.width / 2) * bounds.size.width
            center_y = bounds.origin.y + (1 - box.origin.y - box.size.height / 2) * bounds.size.height
            items.append({"text": candidates[0].string()[:240],
                          "x": round(center_x), "y": round(center_y)})
        items.sort(key=lambda item: (item["y"], item["x"]))
        return {"display": "main", "width": round(bounds.size.width), "height": round(bounds.size.height),
                "text_items": items[:80], "truncated": len(items) > 80}
    except subprocess.TimeoutExpired:
        error = "capture_timeout" if stage == "capture" else "image_resize_timeout"
        action = "屏幕截图" if stage == "capture" else "截图缩放"
        return {"ok": False, "error": error, "stage": stage,
                "detail": f"阶段 {stage}：{action}超时。"}
    except Exception as error:
        return {"ok": False, "error": "screen_read_failed", "stage": stage,
                "exception_type": type(error).__name__,
                "detail": f"阶段 {stage}；{type(error).__name__}: {str(error)[:300] or '未提供错误详情。'}"}
    finally:
        try:
            os.unlink(image_path)
        except FileNotFoundError:
            pass


class ClickArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)


class TypeTextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)


class KeyName(StrEnum):
    enter = "enter"
    tab = "tab"
    escape = "escape"
    backspace = "backspace"
    delete = "delete"
    space = "space"
    left = "left"
    right = "right"
    up = "up"
    down = "down"


class KeyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: KeyName


_KEYCODES = {
    KeyName.enter: 36, KeyName.tab: 48, KeyName.space: 49, KeyName.backspace: 51,
    KeyName.escape: 53, KeyName.delete: 117, KeyName.left: 123, KeyName.right: 124,
    KeyName.down: 125, KeyName.up: 126,
}


def _post_event_check():
    status = _permissions()
    if status["install_required"]:
        return {"ok": False, "error": "dependency_missing", "detail": status["instructions"]}
    if not status["input_control"]:
        return _permission_error("input_control")
    return None


def click_screen(x: int, y: int) -> dict:
    permission = _post_event_check()
    if permission:
        return permission
    _, quartz, _ = _frameworks()
    bounds = quartz.CGDisplayBounds(quartz.CGMainDisplayID())
    if not (bounds.origin.x <= x < bounds.origin.x + bounds.size.width
            and bounds.origin.y <= y < bounds.origin.y + bounds.size.height):
        return {"ok": False, "error": "coordinates_out_of_bounds", "detail": "坐标超出主显示器范围。请先读取屏幕文字和坐标。"}
    point = quartz.CGPointMake(x, y)
    down = quartz.CGEventCreateMouseEvent(None, quartz.kCGEventLeftMouseDown, point, quartz.kCGMouseButtonLeft)
    up = quartz.CGEventCreateMouseEvent(None, quartz.kCGEventLeftMouseUp, point, quartz.kCGMouseButtonLeft)
    if down is None or up is None:
        return {"ok": False, "error": "input_failed", "detail": "无法创建鼠标事件。"}
    quartz.CGEventPost(quartz.kCGHIDEventTap, down)
    quartz.CGEventPost(quartz.kCGHIDEventTap, up)
    return {"clicked": True, "x": x, "y": y}


def type_screen_text(text: str) -> dict:
    permission = _post_event_check()
    if permission:
        return permission
    if "\x00" in text:
        return {"ok": False, "error": "invalid_text", "detail": "输入文字不能包含 NUL 字符。"}
    _, quartz, _ = _frameworks()
    chunks = []
    current = []
    units = 0
    for char in text:
        char_units = 2 if ord(char) > 0xFFFF else 1
        if units + char_units > 20:
            chunks.append(("".join(current), units))
            current, units = [], 0
        current.append(char)
        units += char_units
    if current:
        chunks.append(("".join(current), units))
    for chunk, unit_count in chunks:
        down = quartz.CGEventCreateKeyboardEvent(None, 0, True)
        up = quartz.CGEventCreateKeyboardEvent(None, 0, False)
        if down is None or up is None:
            return {"ok": False, "error": "input_failed", "detail": "无法创建键盘事件。"}
        quartz.CGEventKeyboardSetUnicodeString(down, unit_count, chunk)
        quartz.CGEventPost(quartz.kCGHIDEventTap, down)
        quartz.CGEventPost(quartz.kCGHIDEventTap, up)
    return {"typed_characters": len(text)}


def press_screen_key(key: KeyName) -> dict:
    permission = _post_event_check()
    if permission:
        return permission
    _, quartz, _ = _frameworks()
    code = _KEYCODES[key]
    down = quartz.CGEventCreateKeyboardEvent(None, code, True)
    up = quartz.CGEventCreateKeyboardEvent(None, code, False)
    if down is None or up is None:
        return {"ok": False, "error": "input_failed", "detail": "无法创建键盘事件。"}
    quartz.CGEventPost(quartz.kCGHIDEventTap, down)
    quartz.CGEventPost(quartz.kCGHIDEventTap, up)
    return {"pressed": key.value}


def screen_tools() -> list[Tool]:
    async def check_permissions():
        return permission_status()

    async def read_screen():
        result = await asyncio.to_thread(capture_screen_text)
        if result.get("ok") is False:
            print(f"[Screen diagnostic] {result.get('detail', result.get('error', 'unknown error'))}")
        return result

    async def click(x: int, y: int):
        return click_screen(x, y)

    async def type_text(text: str):
        return type_screen_text(text)

    async def press_key(key: KeyName):
        return press_screen_key(key)

    return [
        Tool("check_macos_permissions", "检查当前 JARVIS 进程的屏幕录制和辅助功能输入权限", NoArguments,
             check_permissions, Risk.SAFE),
        Tool("read_screen_text", "读取主显示器屏幕文字及各文字区域中心坐标；屏幕内容会发送给模型", NoArguments,
             read_screen, Risk.CONFIRM, timeout=60),
        Tool("click_screen", "在主显示器指定坐标单击鼠标左键", ClickArguments, click, Risk.CONFIRM),
        Tool("type_screen_text", "向当前焦点输入最多 500 个字符", TypeTextArguments, type_text, Risk.CONFIRM),
        Tool("press_screen_key", "按下固定白名单按键：enter、tab、escape、backspace、delete、space、方向键", KeyArguments,
             press_key, Risk.CONFIRM),
    ]
