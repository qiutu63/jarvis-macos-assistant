"""Workspace-only file operations with component-wise no-follow traversal."""
import os
import secrets
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.permissions.policy import Risk
from app.tools.base import Tool


class PathArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)


class WriteArguments(PathArguments):
    content: str = Field(max_length=100_000)


class ListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default=".", min_length=1, max_length=1024)


class Workspace:
    def __init__(self, root: Path):
        requested = root.expanduser()
        if requested.is_symlink():
            raise ValueError("工作目录不能是符号链接")
        self.root = requested.resolve()

    def _ensure_root(self) -> None:
        # Create lazily, after the executor has received local confirmation.
        if self.root.is_symlink():
            raise ValueError("工作目录不能是符号链接")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir() or self.root.is_symlink():
            raise ValueError("工作目录必须是普通目录")

    @staticmethod
    def _parts(path: str) -> tuple[str, ...]:
        if "\\" in path or "\x00" in path or path.startswith("/"):
            raise ValueError("路径必须是工作目录内的相对路径")
        parts = tuple(path.split("/"))
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("路径包含不允许的组件")
        return parts

    def _open_parent(self, parts: tuple[str, ...]) -> tuple[int, str]:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.root, flags)
        try:
            for component in parts[:-1]:
                next_fd = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd, parts[-1]
        except Exception:
            os.close(fd)
            raise

    def list_dir(self, path: str = ".") -> list[dict]:
        parts = () if path == "." else self._parts(path)
        self._ensure_root()
        if path == ".":
            fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        else:
            parent, leaf = self._open_parent(parts)
            try:
                fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
            finally:
                os.close(parent)
        try:
            entries = []
            for name in sorted(os.listdir(fd))[:500]:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                entries.append({"name": name, "type": "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"})
            return entries
        finally:
            os.close(fd)

    def read_file(self, path: str) -> dict:
        parts = self._parts(path)
        self._ensure_root()
        parent, leaf = self._open_parent(parts)
        try:
            fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
        finally:
            os.close(parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 100_000:
                raise ValueError("仅支持读取不超过 100 KB 的普通文件")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                content = stream.read(100_001)
                if len(content.encode("utf-8")) > 100_000:
                    raise ValueError("文件超过 100 KB 限制")
                return {"path": path, "content": content}
        except UnicodeDecodeError as exc:
            raise ValueError("文件必须是 UTF-8 文本") from exc

    def write_file(self, path: str, content: str) -> dict:
        parts = self._parts(path)
        self._ensure_root()
        parent, leaf = self._open_parent(parts)
        temporary = None
        try:
            # Atomic replace never follows a pre-existing symlink or hard link.
            for _ in range(10):
                temporary = f".jarvis-{secrets.token_hex(12)}"
                try:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent)
                    break
                except FileExistsError:
                    continue
            else:
                raise OSError("无法创建临时文件")
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
            return {"path": path, "bytes_written": len(content.encode("utf-8"))}
        finally:
            if temporary:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
            os.close(parent)


def workspace_tools(root: Path) -> list[Tool]:
    workspace = Workspace(root)

    async def list_directory(path: str = "."):
        return {"entries": workspace.list_dir(path)}

    async def read_file(path: str):
        return workspace.read_file(path)

    async def write_file(path: str, content: str):
        return workspace.write_file(path, content)

    return [
        Tool("list_workspace", "列出 ~/JARVIS_Workspace 内的目录项", ListArguments, list_directory, Risk.CONFIRM),
        Tool("read_workspace_file", "读取工作区内 UTF-8 文本文件（最多 100 KB）", PathArguments, read_file, Risk.CONFIRM),
        Tool("write_workspace_file", "在工作区内原子创建或替换 UTF-8 文本文件（最多 100 KB）", WriteArguments, write_file, Risk.CONFIRM),
    ]
