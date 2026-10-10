import argparse
import asyncio
import getpass
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from app.agent.core import Agent
from app.agent.executor import Executor
from app.agent.memory import MemoryStore
from app.config.settings import ROOT, load_settings
from app.events.bus import EventBus
from app.mcp.client import connect_mcp_servers
from app.providers.base import ProviderError
from app.providers.factory import create_provider
from app.tools.builtin import build_registry
from app.tools.browser import close_browser
from app.voice import speak, transcribe


async def confirm(name: str, args: dict) -> bool:
    try:
        reply = input(f"[Waiting] 确认执行 {name} {json.dumps(args, ensure_ascii=False)}？输入 yes 同意：")
        approved = reply.strip().lower() == "yes"
        print(f"[Audit] {name}: {'approved' if approved else 'denied'}")
        return approved
    except EOFError:
        print(f"[Audit] {name}: denied (no local input)")
        return False


async def run_cli(options) -> int:
    try:
        settings = load_settings(provider=options.provider)
        provider = create_provider(settings)
    except (ValueError, OSError):
        print("配置错误：请检查 config/config.yaml，以及 .env 中所选 Provider 的 API_KEY、BASE_URL 和 MODEL。")
        return 2
    registry = build_registry(settings.workspace)
    bus = EventBus()
    bus.subscribe(lambda event: print(f"[{event.state}] {event.detail}"))
    memory_path = os.getenv("JARVIS_MEMORY_PATH")
    try:
        memory = MemoryStore(memory_path, history_turns=settings.history_turns)
    except (OSError, ValueError):
        print("本机记忆数据库不可用：请检查记忆目录权限、路径和符号链接设置。")
        await provider.close()
        return 2
    mcp_connections = await connect_mcp_servers(settings.mcp_servers, registry)
    if settings.mcp_servers:
        print(f"MCP 外部服务：已连接 {len(mcp_connections)}/{len(settings.mcp_servers)} 个；工具调用均需本机确认。")
    agent = Agent(provider, registry, max_steps=settings.max_steps, history_turns=settings.history_turns,
                  bus=bus, executor=Executor(registry, settings.tool_timeout, confirm), memory_store=memory)
    label = "离线演示 · 无真实 LLM" if settings.provider == "mock" else f"{settings.provider} / {settings.model}"
    print(f"JARVIS | {label}")
    print("/exit /status /tools /memory /reset /remember 文本 /memories /forget ID|all /task save 标题 | 笔记 /tasks /task delete ID /voice [zh|en] /speak")
    last_response = ""
    try:
        while True:
            try:
                text = options.once if options.once is not None else input("JARVIS > ")
            except EOFError:
                break
            text = text.strip()
            if text == "/exit":
                break
            if text == "/status":
                print(f"状态：{agent.state.value} | {label} | 工作目录：{settings.workspace}")
            elif text == "/tools":
                print("\n".join(registry.describe()))
            elif text == "/memory":
                short, long, tasks = memory.counts()
                print(f"本机 SQLite 记忆：短期 {short}/{settings.history_turns} 轮，长期 {long} 条，任务 {tasks} 条。")
            elif text == "/reset":
                agent.reset()
                print("短期上下文已清空。")
            elif text.startswith("/remember "):
                fact = text[len("/remember "):].strip()
                if not fact or len(fact) > 2000:
                    print("用法：/remember 要保存的事实（最多 2000 字符）")
                else:
                    item_id = memory.save_fact(fact)
                    print(f"长期记忆已保存（ID {item_id}）。")
            elif text == "/memories":
                items = memory.facts()
                print("\n".join(f"{item['id']}: {item['fact']}" for item in items) if items else "没有长期记忆。")
            elif text.startswith("/forget "):
                target = text[len("/forget "):].strip()
                if target == "all":
                    memory.clear_all()
                    agent.history.clear()
                    print("短期、长期和任务记忆已全部清除。")
                else:
                    try:
                        deleted = memory.delete_fact(int(target))
                    except ValueError:
                        deleted = False
                    print("长期记忆已删除。" if deleted else "未找到该长期记忆 ID。")
            elif text.startswith("/task save "):
                payload = text[len("/task save "):]
                title, separator, note = payload.partition("|")
                title, note = title.strip(), note.strip()
                if not separator or not title or not note or len(title) > 200 or len(note) > 4000:
                    print("用法：/task save 标题 | 任务笔记（标题最多 200、笔记最多 4000 字符）")
                else:
                    item_id = memory.save_task(title, note)
                    print(f"任务记忆已保存（ID {item_id}）。")
            elif text == "/tasks":
                items = memory.tasks()
                print("\n".join(f"{item['id']}: {item['title']} — {item['note']}" for item in items)
                      if items else "没有任务记忆。")
            elif text.startswith("/task delete "):
                try:
                    deleted = memory.delete_task(int(text[len("/task delete "):].strip()))
                except ValueError:
                    deleted = False
                print("任务记忆已删除。" if deleted else "未找到该任务 ID。")
            elif text == "/voice" or text.startswith("/voice "):
                language = text.partition(" ")[2].strip() or "zh"
                locale = {"zh": "zh-CN", "en": "en-US"}.get(language)
                if locale is None:
                    print("用法：/voice [zh|en]")
                    continue
                try:
                    spoken = transcribe(locale)
                    print(f"[Voice] 识别结果：{spoken}")
                    last_response = await agent.run(spoken)
                    print("JARVIS:", last_response)
                except (ProviderError, RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                    print(f"[Voice] {error}")
            elif text == "/speak":
                if not last_response:
                    print("还没有可朗读的 JARVIS 回复。")
                else:
                    try:
                        speak(last_response)
                    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                        print(f"[Voice] 朗读失败：{error}")
            elif text.startswith("/"):
                print("未知命令。查看启动提示中的记忆命令，或使用 /voice [zh|en] /speak。")
            elif text:
                try:
                    last_response = await agent.run(text)
                    print("JARVIS:", last_response)
                except (ProviderError, RuntimeError, ValueError) as error:
                    print(f"JARVIS: {error}")
                    if options.once is not None:
                        return 1
                except Exception:
                    print("JARVIS: 内部错误，任务已停止；请运行测试检查当前安装。")
                    if options.once is not None:
                        return 1
            if options.once is not None:
                break
    finally:
        try:
            await close_browser()
        finally:
            try:
                for connection in mcp_connections:
                    await connection.close()
            finally:
                await provider.close()
    return 0


def _dotenv_value(value: str) -> str:
    # dotenv's double-quoted format accepts JSON-style escaping for these values.
    return json.dumps(value, ensure_ascii=False)


def setup_provider(root: Path = ROOT, *, input_fn=input, secret_fn=getpass.getpass) -> Path:
    """Collect credentials locally and atomically write a private .env file."""
    target = root / ".env"
    if target.exists():
        raise FileExistsError(".env 已存在；为避免覆盖现有密钥，请先在本机编辑它。")
    provider = input_fn("选择模型服务商（openai/doubao/ollama）：").strip().lower()
    if provider not in ("openai", "doubao", "ollama"):
        raise ValueError("服务商必须是 openai、doubao 或 ollama")
    prefix = provider.upper()
    default_url = {"openai": "https://api.openai.com/v1", "ollama": "https://ollama.com/v1"}.get(provider, "")
    base_url = input_fn(f"{prefix} Base URL" + (f" [{default_url}]" if default_url else "") + ": ").strip() or default_url
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL 必须是无凭据、无查询参数的 HTTPS 地址")
    model = input_fn(f"{prefix} 模型 ID：").strip()
    api_key = secret_fn(f"{prefix} API Key（输入不回显）：").strip()
    if not model or not api_key or "\n" in api_key or "\r" in api_key:
        raise ValueError("模型 ID 和单行 API Key 均不能为空")
    values = {"JARVIS_PROVIDER": provider, f"{prefix}_BASE_URL": base_url,
              f"{prefix}_MODEL": model, f"{prefix}_API_KEY": api_key}
    content = "# Local credentials; never commit this file.\n" + "".join(
        f"{key}={_dotenv_value(value)}\n" for key, value in values.items())
    root.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".env.", dir=root, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # Refuse a concurrent overwrite as well as one present at startup.
        if target.exists():
            raise FileExistsError(".env 在配置期间被创建；为避免覆盖，请检查该文件。")
        os.link(temporary, target)
        target.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS macOS personal assistant")
    parser.add_argument("--provider", choices=["mock", "openai", "doubao", "ollama"])
    parser.add_argument("--once", help="执行一次后退出")
    parser.add_argument("--setup", action="store_true", help="在本机安全配置真实模型密钥")
    parser.add_argument("--verbose", action="store_true", help="输出不含任务正文的事件日志")
    options = parser.parse_args()
    if options.setup:
        try:
            path = setup_provider()
            print(f"模型配置已保存在 {path}（权限 600）。密钥输入未回显。")
            print("现在运行：python -m app.main --once '你好，请简短介绍自己'")
        except (ValueError, FileExistsError, OSError) as error:
            print(f"配置未完成：{error}")
            raise SystemExit(2)
        return
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("jarvis").setLevel(logging.INFO if options.verbose else logging.WARNING)
    try:
        code = asyncio.run(run_cli(options))
    except KeyboardInterrupt:
        print("\nJARVIS 已停止。")
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
