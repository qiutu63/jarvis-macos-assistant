"""One-request JSON Lines bridge used by the Tauri desktop pet.

This development bridge intentionally starts a fixed Python module and exposes
only the existing Agent loop and its existing local confirmation callback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import subprocess
import sys
import threading
import uuid

from app.agent.core import Agent
from app.agent.executor import Executor
from app.agent.memory import MemoryStore
from app.config.settings import load_settings
from app.events.bus import Event, EventBus
from app.mcp.client import connect_mcp_servers
from app.providers.factory import create_provider
from app.tools.builtin import build_registry
from app.tools.browser import close_browser

_output_lock = threading.Lock()


def emit(event_type: str, **payload: object) -> None:
    with _output_lock:
        print(json.dumps({"type": event_type, **payload}, ensure_ascii=False), flush=True)


def _prepare_voice(install: bool) -> None:
    from app.voice import _build_helper

    executable = _build_helper()
    locale = "zh-CN"
    status = subprocess.run(
        [str(executable), "asset-status", locale], capture_output=True, text=True, timeout=45, check=False,
    )
    if status.returncode:
        raise RuntimeError(status.stderr.strip() or "无法检查本机语音模型状态。")
    model_status = status.stdout.strip()
    if model_status == "installed" or model_status == "unsupported" or not install:
        emit("voice_prepared", status=model_status)
        return
    if model_status not in {"supported", "downloading"}:
        raise RuntimeError(f"无法使用本机语音模型（状态：{model_status or 'unknown'}）。")
    emit("voice_installing", locale=locale)
    result = subprocess.run(
        [str(executable), "install-assets", locale], capture_output=True, text=True, timeout=600, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "本机语音模型下载或安装失败。")
    emit("voice_prepared", status="installed")


async def _confirm(name: str, args: dict) -> bool:
    request_id = str(uuid.uuid4())
    emit("confirmation_required", id=request_id, name=name, args=args)
    try:
        raw = await asyncio.to_thread(sys.stdin.readline)
        reply = json.loads(raw)
        return (reply.get("type") == "confirmation_response"
                and reply.get("id") == request_id
                and reply.get("approved") is True)
    except (EOFError, json.JSONDecodeError, AttributeError):
        return False


@dataclass
class AgentRuntime:
    agent: Agent
    provider: object
    mcp_connections: list

    async def close(self) -> None:
        try:
            await close_browser()
        except Exception:
            pass
        for connection in self.mcp_connections:
            try:
                await connection.close()
            except Exception:
                pass
        await self.provider.close()


async def _create_runtime() -> AgentRuntime:
    settings = load_settings()
    provider = create_provider(settings)
    mcp_connections = []
    try:
        registry = build_registry(settings.workspace)
        mcp_connections = await connect_mcp_servers(settings.mcp_servers, registry)
        if settings.mcp_servers:
            emit("mcp_status", connected=len(mcp_connections), configured=len(settings.mcp_servers))
        bus = EventBus()
        bus.subscribe(lambda event: emit("agent_event", payload={
            "name": event.name, "state": event.state, "detail": event.detail,
        }))
        memory = MemoryStore(history_turns=settings.history_turns)
        agent = Agent(
            provider,
            registry,
            max_steps=settings.max_steps,
            history_turns=settings.history_turns,
            bus=bus,
            executor=Executor(registry, settings.tool_timeout, _confirm),
            memory_store=memory,
        )
        return AgentRuntime(agent, provider, mcp_connections)
    except BaseException:
        for connection in mcp_connections:
            await connection.close()
        await provider.close()
        raise


async def _run(text: str, runtime: AgentRuntime) -> None:
    try:
        answer = await runtime.agent.run(text)
        emit("response", text=answer)
    except Exception:
        emit("error", message="JARVIS 未能完成任务，请检查模型连接和本机配置。")


async def main() -> None:
    runtime = None
    try:
        for raw in sys.stdin:
            try:
                request = json.loads(raw)
                if not isinstance(request, dict):
                    raise ValueError("invalid request")
                if request.get("type") == "voice_prepare":
                    _prepare_voice(request.get("install") is True)
                elif request.get("type") == "memory_action":
                    settings = load_settings()
                    memory = MemoryStore(history_turns=settings.history_turns)
                    action = request.get("action")
                    item_id = request.get("id")
                    if action == "clear_short_term":
                        memory.clear_short_term()
                    elif action == "delete_fact" and isinstance(item_id, int) and item_id > 0:
                        memory.delete_fact(item_id)
                    elif action == "delete_task" and isinstance(item_id, int) and item_id > 0:
                        memory.delete_task(item_id)
                    elif action != "snapshot":
                        emit("error", message="无效的记忆操作")
                        continue
                    short, long, tasks = memory.counts()
                    emit("memory_snapshot", payload={
                        "shortTerm": short, "shortLimit": settings.history_turns,
                        "longTerm": long, "taskCount": tasks,
                        "facts": memory.facts(), "tasks": memory.tasks(),
                        "history": memory.load_short_term(),
                        "provider": settings.provider, "model": settings.model or "离线演示",
                    })
                elif request.get("type") == "run" and isinstance(request.get("text"), str):
                    if runtime is None:
                        runtime = await _create_runtime()
                    await _run(request["text"], runtime)
                else:
                    emit("error", message="无效的本机 Agent 请求")
            except (json.JSONDecodeError, AttributeError, ValueError):
                emit("error", message="无效的本机 Agent 请求")
            except (RuntimeError, OSError) as error:
                emit("error", message=str(error))
            except Exception:
                emit("error", message="JARVIS 未能完成任务，请检查模型连接和本机配置。")
            finally:
                emit("request_complete")
    finally:
        if runtime is not None:
            await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
