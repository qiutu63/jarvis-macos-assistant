# Phase 7：桌面宠物

日期：2026-10-08（Asia/Shanghai）

## 已实现

- 根据用户确认的视觉方向，使用原创蓝色粒子全息虚拟人物立绘（`ui/assets/jarvis-particle-companion-v2.png`，971×1620 RGBA），制作可浮动、常驻最前、无边框的 Tauri 2 + Vue 桌面窗口。静态稿位于 `ui/hud-prototype.html`；原生前端位于 `desktop/`。
- 窗口和 WebView 均配置透明背景，并保持轻量对话气泡、待命状态、快捷入口和可展开对话区。对话发送到现有 JARVIS Agent；Python bridge 以 JSON Lines 运行在固定项目目录和 `.venv/bin/python` 中，不开放本机网络端口。
- 工具需要确认时，前端展示工具名和参数，并让用户选择“允许这次”或“拒绝”。Rust 仅暴露 `run_agent`、`respond_confirmation` 和固定动作枚举的 `memory_action`，没有通用 Shell 执行接口。
- 记忆面板连接现有 SQLite，显示短期轮数、长期记忆、任务笔记以及当前 Provider/模型；支持删除单条长期/任务记忆、清空短期对话。数据删除在前端二次确认。新增/编辑记忆仍可通过现有 CLI 显式命令完成。
- 应用启动和刷新记忆面板时，会恢复最近受限轮数的本机短期对话，供用户查看。
- “清空本次显示”仅清理前端对话显示；“清除短期对话记忆”才会删除 SQLite 中的短期历史。
- 本机开发版应用位于 `desktop/src-tauri/target/debug/bundle/macos/JARVIS Desktop Pet.app`。该构建依赖项目根目录的 `.venv`、模型配置和语音辅助程序，不能脱离本项目目录运行。

## 本轮验证

- `npm run build`：通过（Vue 类型检查和前端打包）。
- `cargo check`：通过；Tauri 调试版 `.app` 构建成功并已在本机启动。
- Python JSON Lines bridge 使用 mock Provider 和临时记忆数据库做过一次 smoke run，能返回 Thinking/Planning/Completed 事件及回复。记忆快照 bridge 也完成 smoke run；已在本机桌面实际打开记忆面板，验证它读取到 3 轮短期、1 条长期和 1 条任务记忆，并显示当前 `ollama / gpt-oss:20b`。
- macOS 自动化截图对透明窗口会以白色作为截图底色，因此截图不作为桌面透明合成的验收证据。窗口配置透明；已增加全局光标区域检测，让伙伴、气泡、对话/记忆面板、快捷栏和拖动把手接收交互，其余透明区域调用 Tauri 点击穿透。需在真实桌面上确认底层应用确实收到穿透点击。

## 尚未完成

- 应用安装/签名流程未实现。
- 当前“清空本次显示”只清除前端显示；记忆面板中的短期清除会删除 SQLite 中的短期历史。
- 默认桌面窗口依赖 macOS 私有 API 开启透明；Tauri 官方说明这会导致应用无法通过 Mac App Store 审核。若目标改为上架，需要改成公共 API 支持的半透明效果或重做窗口方案。
- 自动截图白底无法证明透明效果；后续验收时应在桌面壁纸/其他窗口上直接观察实际合成。

## 更新：桌面连续语音对话

日期：2026-10-09（Asia/Shanghai）

- 点击快捷栏语音键后进入连续语音对话，再次点击结束；此按键对话模式不启用后台唤醒。独立唤醒入口见 `PHASE8_REPORT.md`。
- 沿用 Phase 5 的 SpeechAnalyzer 辅助程序。本机音量阈值和约 1.5 秒静音间隔用于判断一句话结束；单轮最多 25 秒，无语音时 10 秒后重新聆听。
- 识别文字自动发送给当前 Agent，回复自动语音朗读；朗读完成后再重新开始监听，减少回声误识别。工具确认仍需用户在界面点选。
- 首次使用会询问是否从 Apple 下载缺失的中文语音模型。录音采集和识别在本机完成，不保存录音；识别文字会进入当前 Provider 上下文。
- 麦克风权限提示引导到系统设置 → 隐私与安全性 → 麦克风。
- 唤醒后的语音对话、普通语音轮次和语音结束不再自动展开聊天面板；消息仍留在对话历史中，用户可手动展开查看。需要视觉核对的工具确认仍会自动展开确认卡。
- 前端生产构建、Rust 检查和 Python 语法检查通过。桌面连续语音首次实测发现主应用缺少 `NSMicrophoneUsageDescription`，macOS TCC 因此终止语音辅助程序；已在 `desktop/src-tauri/Info.plist` 补充用途说明并重新构建。
- 修复后在桌面版实测：语音按钮进入聆听，成功识别“你好”，文字自动发送到 Ollama `gpt-oss:20b`，模型回答并通过本机 TTS 朗读，随后恢复聆听；点击结束后回到待命。长回复已提交时，停止监听不会取消该回复，回复会完成朗读后保持待命。

## 更新：桌面语音输出

- Agent 回复通过 macOS `AVSpeechSynthesizer` 在本机朗读；优先选用设备上已安装的高品质中文语音，稍微放慢语速并保留自然停顿。朗读前会跳过 Markdown 格式标记、代码块和链接地址。快捷栏扬声器按钮控制自动朗读，默认开启，偏好保存于当前 WebView 的本地存储。
- TTS 不经网络；朗读文本不写音频文件。
- 前端构建和 Rust 检查通过。真实桌面播放效果仍需用户在应用中验收。

## 更新：常驻 Agent 桥接进程

- Tauri 桌面端现在复用一个长期运行的 Python bridge、Agent、Provider 和 MCP stdio 服务；对话轮次间保留进程内 Agent 状态，并通过 SQLite 保留短期历史。
- JSON Lines 请求以 `request_complete` 明确分隔；确认响应继续走同一管道。Bridge EOF 时关闭 MCP 服务和 Provider。
- Python bridge 双请求子进程测试已覆盖；桌面实际 UI 连续多轮及工具确认仍需本机验收。

## 更新：桌面发布构建检查

日期：2026-10-09（Asia/Shanghai）

- 运行 `npm run tauri build` 成功，生成 release `.app` 和 Apple Silicon `.dmg`。本机启动新 `.app` 后，界面已显示连续语音按钮；旧 debug `.app` 仍显示过时的“语音稍后接入”，不应用于验收当前功能。
- `.app` 和 `.dmg` 目前只是工作区构建产物，不是独立安装版：Rust 后端用编译时项目路径启动 `.venv/bin/python`，并从项目 `.build/JARVIS Voice.app` 调用语音辅助程序；模型配置也保存在项目根目录。因此移动 DMG 到另一台 Mac 前，仍需完成运行时/资源打包和配置初始化。
- 当前构建未进行 Developer ID 签名或公证。应用仍依赖项目源码、`.venv`、`.env` 和 `.build/JARVIS Voice.app`，DMG 暂不能独立安装使用。
