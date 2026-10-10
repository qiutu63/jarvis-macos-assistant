import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_cli_session(tmp_path):
    env = dict(os.environ, JARVIS_MEMORY_PATH=str(tmp_path / "memory.sqlite3"))
    result = subprocess.run([sys.executable, "-m", "app.main", "--provider", "mock"],
                            input="/status\n/tools\n你好\n当前时间\n/memory\n/reset\n/memory\n/exit\n",
                            env=env, text=True, capture_output=True, cwd=ROOT, timeout=10)
    assert result.returncode == 0
    for expected in ("离线演示", "current_time [SAFE]", "[Observing] 成功", "短期 2/8", "短期 0/8"):
        assert expected in result.stdout


def test_missing_real_config_is_not_mock_success():
    env = dict(os.environ, OPENAI_API_KEY="", OPENAI_MODEL="")
    result = subprocess.run([sys.executable, "-m", "app.main", "--provider", "openai", "--once", "你好"],
                            env=env, text=True, capture_output=True, cwd=ROOT, timeout=10)
    assert result.returncode == 2
    assert "配置错误" in result.stdout
    assert "离线演示" not in result.stdout
