"""Build an ad-hoc signed macOS app bundle for the optional KWS candidate."""
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scripts/kws-helper"
BINARY = PACKAGE / ".build/release/JarvisKeywordSpotter"
MODEL = ROOT / ".build/sherpa-kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
APP = ROOT / ".build/JARVIS KWS Candidate.app"


def run(args: list[str], timeout: int = 600) -> None:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr.strip() or result.stdout.strip())[-3000:])


def main() -> None:
    if not shutil.which("swift"):
        raise RuntimeError("缺少 Swift 编译器，请先安装 Xcode Command Line Tools。")
    run(["swift", "build", "--package-path", str(PACKAGE), "-c", "release"])
    if not BINARY.is_file():
        raise RuntimeError(f"SwiftPM 没有生成预期程序：{BINARY}")
    if not (MODEL / "jarvis-keywords.txt").is_file():
        raise RuntimeError("请先运行 scripts/setup_kws_model.py 准备模型和关键词。")

    if APP.exists():
        shutil.rmtree(APP)
    contents = APP / "Contents"
    executable_dir = contents / "MacOS"
    resources = contents / "Resources"
    executable_dir.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.copy2(BINARY, executable_dir / "JarvisKWS")
    shutil.copytree(MODEL, resources / "KWSModel", ignore=shutil.ignore_patterns("test_wavs", "*.phone"))
    plist = {
        "CFBundleExecutable": "JarvisKWS",
        "CFBundleIdentifier": "com.jarvis.kws.candidate",
        "CFBundleName": "JARVIS KWS Candidate",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": "JARVIS 使用麦克风在本机测试中文唤醒词检测；音频不会上传或保存。",
    }
    with (contents / "Info.plist").open("wb") as output:
        plistlib.dump(plist, output)
    run(["/usr/bin/codesign", "--force", "--sign", "-", str(APP)], timeout=30)
    print(f"候选程序已构建：{APP}")
    print("启动检测：在终端运行 scripts/run_kws_candidate.command；按 Ctrl+C 停止。")


if __name__ == "__main__":
    main()
