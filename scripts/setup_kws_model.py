"""Download the local Sherpa-ONNX Chinese/English KWS model into .build."""
from __future__ import annotations

import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
MODEL_ROOT = ROOT / ".build" / "sherpa-kws" / MODEL_NAME
ARCHIVE = ROOT / ".build" / "sherpa-kws-model.tar.bz2"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    f"{MODEL_NAME}.tar.bz2"
)


def main() -> None:
    if not (MODEL_ROOT.is_dir() and (MODEL_ROOT / "tokens.txt").is_file()):
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        print("正在从 Sherpa-ONNX 官方发布页下载关键词模型（约 38 MB）……")
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "JARVIS-KWS-setup"})
        with urllib.request.urlopen(request, timeout=120) as response, ARCHIVE.open("wb") as output:
            shutil.copyfileobj(response, output)

        destination = ARCHIVE.parent.resolve()
        with tarfile.open(ARCHIVE, "r:bz2") as archive:
            for member in archive.getmembers():
                path = (destination / member.name).resolve()
                if path != destination and destination not in path.parents:
                    raise RuntimeError(f"模型压缩包包含无效路径：{member.name}")
            archive.extractall(destination, filter="data")
        ARCHIVE.unlink(missing_ok=True)

    required = [
        "encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
        "decoder-epoch-13-avg-2-chunk-16-left-64.onnx",
        "joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
        "tokens.txt",
        "en.phone",
    ]
    missing = [name for name in required if not (MODEL_ROOT / name).is_file()]
    if missing:
        raise RuntimeError("模型下载后文件不完整：" + ", ".join(missing))
    shutil.copy2(ROOT / "scripts/kws-helper/resources/keywords.txt", MODEL_ROOT / "jarvis-keywords.txt")
    print(f"KWS 模型和“贾维斯·零”关键词已准备：{MODEL_ROOT}")


if __name__ == "__main__":
    main()
