import json

import pytest

from app.agent.executor import Executor
from app.permissions.policy import Risk
from app.providers.base import ToolCall
from app.tools.builtin import build_registry
from app.tools.system import OpenAppArguments, TerminalArguments
from app.tools.workspace import Workspace


def test_workspace_writes_atomic_reads_and_rejects_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "nested").mkdir()
    workspace = Workspace(root)
    assert workspace.write_file("nested/note.txt", "你好") == {"path": "nested/note.txt", "bytes_written": 6}
    assert workspace.read_file("nested/note.txt")["content"] == "你好"
    assert workspace.list_dir("nested")[0]["name"] == "note.txt"
    for bad in ("../secret", "/etc/passwd", "nested/../secret", "nested\\secret"):
        with pytest.raises(ValueError):
            workspace.read_file(bad)


def test_workspace_rejects_symlink_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / "link").symlink_to(outside, target_is_directory=True)
    workspace = Workspace(root)
    with pytest.raises(OSError):
        workspace.read_file("link/secret.txt")
    with pytest.raises(OSError):
        workspace.write_file("link/overwrite.txt", "x")


def test_phase2_tools_are_confirmed_or_allowlisted(tmp_path):
    registry = build_registry(tmp_path)
    assert {tool.name for tool in registry._tools.values()} >= {
        "list_workspace", "read_workspace_file", "write_workspace_file", "open_application", "run_terminal"
    }
    assert registry.get("write_workspace_file").risk == Risk.CONFIRM
    assert registry.get("open_application").risk == Risk.CONFIRM
    assert registry.get("run_terminal").risk == Risk.CONFIRM
    with pytest.raises(Exception):
        OpenAppArguments.model_validate({"app": "Arbitrary App"})
    with pytest.raises(Exception):
        TerminalArguments.model_validate({"command": "python -c", "path": "."})


async def test_file_write_requires_local_confirmation(tmp_path):
    registry = build_registry(tmp_path)
    calls = []

    async def deny(name, args):
        calls.append((name, args))
        return False

    result = await Executor(registry, confirm=deny).execute(ToolCall(
        id="write", name="write_workspace_file", arguments=json.dumps({"path": "note.txt", "content": "hello"})
    ))
    assert result["error"] == "confirmation_denied"
    assert calls and not (tmp_path / "note.txt").exists()
