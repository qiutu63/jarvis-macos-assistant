import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

ROOT = Path(__file__).resolve().parents[2]


class MCPServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,19}$")
    command: str = Field(min_length=1, max_length=1024)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=20, gt=0, le=120)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["mock", "openai", "doubao", "ollama"] = "mock"
    workspace: Path = Path("~/JARVIS_Workspace")
    max_steps: int = Field(default=6, ge=1, le=20)
    history_turns: int = Field(default=8, ge=1, le=50)
    request_timeout: float = Field(default=30, gt=0, le=120)
    tool_timeout: float = Field(default=10, gt=0, le=120)
    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    model: str = ""
    mcp_servers: list[MCPServerSettings] = Field(default_factory=list, max_length=8)


def load_settings(root: Path = ROOT, provider: str | None = None) -> Settings:
    load_dotenv(root / ".env", override=False)
    path = root / "config/config.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml 必须是键值配置")
    data["provider"] = provider or os.getenv("JARVIS_PROVIDER") or data.get("provider", "mock")
    settings = Settings.model_validate(data)
    server_names = [server.name for server in settings.mcp_servers]
    if len(server_names) != len(set(server_names)):
        raise ValueError("MCP 服务名称不能重复")
    expected_workspace = Path.home() / "JARVIS_Workspace"
    requested_workspace = settings.workspace.expanduser()
    if requested_workspace != expected_workspace:
        raise ValueError("workspace 固定为 ~/JARVIS_Workspace")
    if requested_workspace.exists() and requested_workspace.is_symlink():
        raise ValueError("~/JARVIS_Workspace 不能是符号链接")
    settings.workspace = requested_workspace
    if settings.provider != "mock":
        prefix = settings.provider.upper()
        settings.api_key = SecretStr(os.getenv(f"{prefix}_API_KEY", ""))
        settings.model = os.getenv(f"{prefix}_MODEL", "").strip()
        defaults = {"OPENAI": "https://api.openai.com/v1", "OLLAMA": "https://ollama.com/v1"}
        settings.base_url = os.getenv(f"{prefix}_BASE_URL", defaults.get(prefix, "")).strip()
        if not all([settings.api_key.get_secret_value(), settings.model, settings.base_url]):
            raise ValueError(f"请在 .env 配置 {prefix}_API_KEY、{prefix}_MODEL、{prefix}_BASE_URL")
    return settings
