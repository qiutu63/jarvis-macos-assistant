"""macOS push-key CLI speech input and system speech output."""
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / ".build" / "JARVIS Voice.app"
EXECUTABLE = APP / "Contents" / "MacOS" / "JARVISVoice"
SOURCE = ROOT / "scripts" / "jarvis_voice.swift"


def _build_helper() -> Path:
    if __import__("sys").platform != "darwin":
        raise RuntimeError("语音功能仅支持 macOS。")
    if EXECUTABLE.exists() and EXECUTABLE.stat().st_mtime >= SOURCE.stat().st_mtime:
        return EXECUTABLE
    if not __import__("shutil").which("swiftc"):
        raise RuntimeError("缺少 Swift 编译器。请先在终端执行 xcode-select --install 安装 Xcode Command Line Tools。")
    contents = APP / "Contents"
    executable_dir = contents / "MacOS"
    executable_dir.mkdir(parents=True, exist_ok=True)
    module_cache = ROOT / ".build" / "SwiftModuleCache"
    module_cache.mkdir(parents=True, exist_ok=True)
    plist = {
        "CFBundleExecutable": "JARVISVoice",
        "CFBundleIdentifier": "com.jarvis.cli.voice",
        "CFBundleName": "JARVIS Voice",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": "JARVIS 使用麦克风在本机检测唤醒词，并处理你主动发起的语音对话；音频不会上传或保存。",
    }
    with (contents / "Info.plist").open("wb") as output:
        plistlib.dump(plist, output)
    result = subprocess.run(
        ["swiftc", "-parse-as-library", "-module-cache-path", str(module_cache), "-O",
         str(SOURCE), "-o", str(EXECUTABLE)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if result.returncode:
        raise RuntimeError("语音辅助程序编译失败：" + (result.stderr.strip()[-1000:] or "未知错误"))
    signed = subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", str(APP)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if signed.returncode:
        raise RuntimeError("语音辅助程序签名失败：" + (signed.stderr.strip()[-500:] or "未知错误"))
    return EXECUTABLE


def transcribe(locale: str = "zh-CN") -> str:
    if locale not in {"zh-CN", "en-US"}:
        raise ValueError("语音识别语言只支持 zh-CN 或 en-US。")
    executable = _build_helper()
    status = subprocess.run([str(executable), "asset-status", locale], capture_output=True,
                            text=True, timeout=45, check=False)
    if status.returncode:
        raise RuntimeError(status.stderr.strip() or "无法检查本机语音模型状态。")
    model_status = status.stdout.strip()
    if model_status == "unsupported":
        raise RuntimeError(f"当前设备不支持 {locale} 的本机语音模型。")
    if model_status != "installed":
        if model_status not in {"supported", "downloading"}:
            raise RuntimeError(f"无法使用本机语音模型（状态：{model_status or 'unknown'}）。")
        print(f"[Voice] {locale} 本机语音模型尚未安装。需要从 Apple 下载模型；录音不会上传。")
        if input("同意下载请输入 yes：").strip().lower() != "yes":
            raise RuntimeError("未下载语音模型，已取消语音输入。")
        print("[Voice] 正在下载并安装模型，请稍候……")
        install = subprocess.run([str(executable), "install-assets", locale], capture_output=True,
                                 text=True, timeout=600, check=False)
        if install.returncode:
            raise RuntimeError(install.stderr.strip() or "本机语音模型下载或安装失败。")
        installed = subprocess.run([str(executable), "asset-status", locale], capture_output=True,
                                   text=True, timeout=45, check=False)
        if installed.returncode or installed.stdout.strip() != "installed":
            raise RuntimeError("语音模型安装后仍不可用，请稍后重试。")
    process = subprocess.Popen([str(executable), "transcribe", locale], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        print("\n[Voice] 录音启动后说话；按回车结束录音并提交给本机识别。最长 30 秒。")
        input("[Voice] 请说话，然后按回车：")
    except (EOFError, KeyboardInterrupt):
        process.terminate()
        process.wait(timeout=5)
        raise RuntimeError("语音输入已取消。")
    output, diagnostics = process.communicate("stop\n", timeout=70)
    if process.returncode:
        raise RuntimeError(diagnostics.strip() or output.strip() or "语音输入失败，辅助程序未提供错误详情。")
    return output.strip()


def speak(text: str) -> None:
    if __import__("sys").platform != "darwin":
        raise RuntimeError("语音朗读仅支持 macOS。")
    if not text.strip() or len(text) > 16000:
        raise ValueError("朗读内容长度必须为 1–16000 个字符。")
    subprocess.run(["/usr/bin/say", "-r", "190", text], check=True, timeout=180)
