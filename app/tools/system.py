"""Small, fixed allowlists for app launching and diagnostic terminal actions."""
import asyncio
import os
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from app.permissions.policy import Risk
from app.tools.base import Tool


class AppName(StrEnum):
    calculator = "Calculator"
    finder = "Finder"
    notes = "Notes"
    safari = "Safari"
    textedit = "TextEdit"


class OpenAppArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: AppName


class OpenInstalledAppArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str

    @field_validator("app_name")
    @classmethod
    def validate_app_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 120 or re.search(r"[/\\\x00-\x1f\x7f]", value):
            raise ValueError("请提供已安装应用的名称，不要传入路径或控制字符")
        return value


class TerminalCommand(StrEnum):
    python_version = "python_version"
    node_version = "node_version"
    git_status = "git_status"


class TerminalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: TerminalCommand


async def _run(argv: list[str], cwd: Path | None = None) -> dict:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": os.path.expanduser("~"), "LANG": "C"}
    process = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env,
                                                   stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    output = stdout.decode("utf-8", errors="replace")[:4000]
    error = stderr.decode("utf-8", errors="replace")[:1000]
    return {"returncode": process.returncode, "stdout": output, "stderr": error}


def system_tools(workspace_root: Path) -> list[Tool]:
    root = workspace_root.expanduser().resolve()

    async def open_app(app: AppName):
        if not Path("/usr/bin/open").is_file():
            raise RuntimeError("macOS open 命令不可用")
        return await _run(["/usr/bin/open", "-a", app.value])

    async def open_installed_app(app_name: str):
        if not Path("/usr/bin/open").is_file():
            raise RuntimeError("macOS open 命令不可用")
        return await _run(["/usr/bin/open", "-a", app_name])

    async def run_terminal(command: TerminalCommand):
        if root.is_symlink():
            raise ValueError("工作目录不能是符号链接")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("工作目录必须是普通目录")
        cwd = root
        if command == TerminalCommand.python_version:
            executable = "/usr/bin/python3"
            argv = [executable, "--version"]
        elif command == TerminalCommand.node_version:
            executable = next((p for p in ("/opt/homebrew/bin/node", "/usr/local/bin/node") if Path(p).is_file()), None)
            if executable is None:
                return {"returncode": 127, "stdout": "", "stderr": "node 不在允许的位置"}
            argv = [executable, "--version"]
        else:
            executable = "/usr/bin/git"
            argv = [executable, "status", "--short", "--branch"]
        return await _run(argv, cwd)

    return [
        Tool("open_application", "打开白名单中的 macOS 应用（Finder、Calculator、Notes、Safari、TextEdit）", OpenAppArguments, open_app, Risk.CONFIRM),
        Tool("open_installed_application", "按名称打开本机已安装的 macOS 应用；只能传应用名，不能传路径", OpenInstalledAppArguments, open_installed_app, Risk.CONFIRM),
        Tool("run_terminal", "运行只读诊断白名单：python_version、node_version 或 git_status；工作目录固定为工作区根目录", TerminalArguments, run_terminal, Risk.CONFIRM),
    ]
