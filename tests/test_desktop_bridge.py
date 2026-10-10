import json
import os
import subprocess
import sys
from pathlib import Path


def test_desktop_bridge_keeps_agent_alive_across_requests(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["JARVIS_PROVIDER"] = "mock"
    env["JARVIS_MEMORY_PATH"] = str(tmp_path / "memory.sqlite3")
    process = subprocess.Popen(
        [sys.executable, "-m", "app.desktop_bridge"],
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        for prompt in ("你好", "当前时间"):
            process.stdin.write(json.dumps({"type": "run", "text": prompt}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            events = []
            while True:
                line = process.stdout.readline()
                assert line, "desktop bridge exited before completing a request"
                event = json.loads(line)
                events.append(event["type"])
                if event["type"] == "request_complete":
                    break
            assert "response" in events
        assert process.poll() is None
    finally:
        process.stdin.close()
        process.wait(timeout=5)

