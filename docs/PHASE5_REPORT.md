# Phase 5 按键语音输入与朗读

日期：2026-10-08（Asia/Shanghai）

## 已实现

- `/voice [zh|en]` 显式开始一段短录音，回车停止并将识别文字提交给 Agent；最长 30 秒。
- 通过带麦克风用途说明的 Swift 辅助 App 请求麦克风访问。
- AVAudioEngine 实时采集，经 SpeechAnalyzer 和 SpeechTranscriber 本机识别；当前支持 `zh-CN`、`en-US`，音频不上传。
- 通过 AssetInventory 检查本机模型。模型缺失时先询问用户，再从 Apple 下载并安装模型资源。
- 原始录音仅存在内存 buffer，不保存录音文件；只把识别文本送给配置的模型 Provider。
- 识别超时时统计麦克风音频 buffer，优先返回已有的部分识别结果，并区分“未采到音频”和“本机 Speech 未返回结果”；报错带具体原因。
- `/speak` 使用 macOS `say` 朗读最近一条 Agent 回复，不自动播放。
- 首次运行时按需调用 Swift 编译器生成 `.build/JARVIS Voice.app`，无需 Python 音频包。

## 用户首次操作

1. 在项目终端激活环境并启动：`source .venv/bin/activate && python -m app.main`。
2. 输入 `/voice`，等待编译；首次使用允许 Terminal 访问麦克风。
3. 看到“录音中”后说话，再按回车；确认识别文字后，它会作为输入发给当前模型。
4. 如需英文识别，输入 `/voice en`。输入 `/speak` 朗读最近回复。
5. 如需调整授权，进入 **系统设置 → 隐私与安全性 → 麦克风**，启用 Terminal。

## 验收状态与限制

代码与辅助程序已在用户 Mac 编译、签名。AssetInventory 检查显示 `zh-CN` 与 `en-US` 模型状态为 supported（需下载），尚未安装；首次 `/voice` 会显示下载提示。真实麦克风与 SpeechAnalyzer 端到端识别仍待用户在终端同意模型安装后验收。模型不可用时会报错停止，不会切换到网络语音识别。`say` 使用当前系统语音设置。
