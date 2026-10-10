# Phase 10：专用关键词检测方案

## 本阶段结论

- 当前唤醒流程在 Swift 辅助程序中反复启动 Apple SpeechAnalyzer，对每段录音做完整转写，再由 Rust 查找“贾维斯·零”。它能把唤醒词后面的同句命令一起交给 Agent，但持续监听时需要运行完整语音识别。
- openWakeWord 官方项目目前仅支持英文，不适合直接检测中文唤醒短语。
- 下一阶段选用 Sherpa-ONNX 的 `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` 作为候选。该模型支持中英关键词、可配置关键词并在本机推理，模型包约 38 MB。

## 实施进度

- 新增独立 SwiftPM helper：`scripts/kws-helper/`，通过 Swift Package Manager 固定使用 Sherpa-ONNX 1.13.8。
- helper 在 macOS 上读取麦克风音频、转换为 16 kHz 单声道并运行关键词检测；通过标准输出报告检测事件，便于后续由桌面端管理子进程。
- `swift build --package-path scripts/kws-helper -c release` 已成功。首次解析依赖会下载 Sherpa/ONNX Runtime 的多个 Apple 平台二进制包（约 135 MB）；这是构建体积和等待时间上的实际成本。
- 新增模型准备脚本 `scripts/setup_kws_model.py`，下载 Sherpa 官方中英 KWS 模型并检查必需文件；用 Sherpa 官方 `text2token` 命令生成了“贾维斯·零”关键词。
- 新增 `scripts/build_kws_helper.py`，把 helper、模型和关键词打包成独立麦克风权限 app：`.build/JARVIS KWS Candidate.app`。这只用于单独验证检测效果。
- 新增 `scripts/run_kws_candidate.command`，可在终端启动候选监听并显示检测到的关键词；按 Ctrl+C 停止。
- KWS helper 现在会在内存中保留最多 12 秒单声道 PCM；命中关键词后继续采音到静音或 8 秒上限，再把缓存交给 Apple SpeechAnalyzer。录音不会写到文件。检测结果为整句转写，因此沿用前端逻辑去掉唤醒短语后，将剩余文字作为初始请求。
- 桌面快捷栏新增独立的 `KWS` 测试按钮；原来的“唤”按钮仍使用 SpeechAnalyzer。桌面应用通过本机子进程控制候选 helper。
- 桌面端 Vue/Rust 构建和 KWS SwiftPM 构建均通过。新桌面 app 已安装到 `/Applications/JARVIS Desktop Pet.app`；旧版本分别备份在 `.build/backups/JARVIS Desktop Pet-before-kws-20261010.app` 和 `.build/backups/JARVIS Desktop Pet-before-kws-switch-20261010.app`。
- 尚未在真实对话中验收同句命令交接、静音边界和误触发；完成这些验证前，不把 KWS 设为默认唤醒方式。输入缓冲的本机转写需要 macOS 27 或更新版本；当前目标机为 macOS 27.0.1。

## 迁移约束

- 关键词检测需要 Sherpa-ONNX 原生运行库；现有辅助程序由 `swiftc` 直接编译单个 Swift 文件，不能直接导入 Sherpa Swift Package。需要单独的 SwiftPM helper 构建入口，并把可执行文件与模型纳入应用构建/首次启动流程。
- 保留现有 macOS 麦克风权限上下文：采音应继续由 `.app` bundle 内的 Swift helper 负责，不转交给 Python 录音库。
- 保留“贾维斯·零”的中英文关键词文本和现有唤醒 UI 事件协议；模型首次下载、校验失败和权限拒绝都应清楚报错。
- 当前行为支持在同一句“贾维斯·零，……指令”里截取唤醒词后的命令。单纯关键词检测只提供“检测到了关键词”，不会提供后续语音转写。迁移实现必须保留一段短音频缓存，在检测命中时把唤醒词之后的音频交给现有本机 SpeechAnalyzer；否则需要改变用户说话方式，不能静默丢弃同句命令。
- 新检测器应作为可回退路径：模型缺失或初始化失败时保留现有 ASR 监听，不影响语音对话和手动控制。

## 下一步验收

在桌面 KWS 测试按钮下验证真实唤醒后同句命令是否完整进入 Agent、是否误触发、静音收尾是否自然、麦克风授权、停止/退出和 CPU 占用；在这些项目通过之前不切换默认监听。

## 参考资料

- [openWakeWord 官方项目](https://github.com/dscripka/openWakeWord)
- [Sherpa-ONNX KWS 文档](https://k2-fsa.github.io/sherpa/onnx/kws/index.html)
- [Sherpa-ONNX 预训练关键词模型](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html)
- [Sherpa-ONNX Swift Package](https://github.com/k2-fsa/sherpa-onnx/blob/master/Package.swift)
