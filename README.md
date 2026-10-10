# JARVIS

运行于 macOS 的个人语音 Agent，包含 Tauri 桌面宠物、连续本机语音对话、本机唤醒监听、SQLite 记忆、受限工具和 MCP stdio 客户端。桌面宠物保留原有粒子立绘，并按待机、监听、思考和朗读状态播放轻微动画。当前项目仍是面向这台 Mac 的源码工程；桌面构建依赖项目根目录、Python 虚拟环境、用户配置及本机语音资源，尚不是可直接拷贝到其他 Mac 的独立安装包。

功能按阶段记录于 `docs/PHASE*_REPORT.md`，整体实现和隐私边界见 `docs/ARCHITECTURE.md`。Phase 11 记录专用关键词检测与原语音识别模式；Phase 12 记录桌面宠物状态动画。当前唤醒方式可在桌面快捷栏切换：`KWS` 使用 Sherpa-ONNX 专用关键词检测，`唤` 使用 Apple SpeechAnalyzer 识别匹配唤醒词。唤醒短语为“贾维斯·零”。

当前默认是明确标注的离线演示，不是真实 LLM。已经实现配置、Provider 抽象、OpenAI/豆包/Ollama Cloud 适配层、Tool Registry、受限 Agent Loop、事件状态和 CLI。工具包括工作区文件、固定应用白名单、固定诊断命令、受限 Playwright 网页浏览、屏幕 OCR，以及需确认的鼠标/键盘输入；不提供任意 Shell 或代码执行。桌面端使用本机 JSON Lines IPC 调用常驻 Python Agent；聊天面板由用户点击伙伴后展开，不会因唤醒而强制打开。

## 在这台 Mac 上启动

当前目录已创建 `.venv`，使用本机已有 Python 3.12.14。系统 `/usr/bin/python3` 是 3.9.6，不能用于本项目。

```bash
cd /path/to/JARVIS
source .venv/bin/activate
python -m app.main
```

也可以双击 `scripts/start.command`，或执行：

```bash
./scripts/start.command
```

输入 `你好` 查看离线演示回复，输入 `当前时间` 验证完整工具循环：

```text
Thinking → Planning → Executing → Observing → Planning → Completed
```

命令：`/exit` 退出；`/status` 状态；`/tools` 工具；`/memory` 查看记忆条数；`/reset` 清空短期上下文；`/remember 文本` 显式保存长期记忆；`/memories` 查看长期记忆；`/forget ID` 删除长期记忆，`/forget all` 清空全部记忆；`/task save 标题 | 笔记` 显式保存任务记忆；`/tasks` 查看任务；`/task delete ID` 删除任务；`/voice [zh|en]` 录音并提交识别文字；`/speak` 朗读最近回复。Ctrl+C 停止程序。

Phase 6 记忆保存在 `~/Library/Application Support/JARVIS/memory.sqlite3`，目录权限为 700、数据库权限为 600。短期记忆仅保存用户消息和最终回复，默认保留最近 8 轮；长期记忆和任务笔记只通过上述显式命令保存。`/reset` 只清短期记忆，`/forget all` 清除三类记忆。SQLite 文件是本机明文，不加密；恢复的短期历史以及长期/任务记忆会随后续请求加入模型上下文，并发送给当前配置的 Provider。用户可通过删除指定条目、`/forget all` 或直接删除数据库文件管理数据。测试可用 `JARVIS_MEMORY_PATH` 指定临时数据库路径。

Phase 7 桌面宠物已实现为 macOS 原生悬浮窗口，设计预览位于 [ui/hud-prototype.html](ui/hud-prototype.html)，实现边界见 `docs/PHASE7_REPORT.md`。开发时在 `desktop/` 执行 `npm run tauri dev`；构建可分发物使用 `npm run tauri build`，输出 `.app` 和 `.dmg`。当前构建仍依赖本项目源码、`.venv`、`.env` 模型配置及本机语音辅助程序/模型，不能单独移动到其他 Mac 使用。窗口常驻最前、无边框并启用透明背景，点击伙伴可展开对话。Agent 由 Rust 后端以固定项目虚拟环境启动，通过 JSON Lines IPC 传递事件；有风险的工具操作仍需逐次确认，语音确认会先朗读操作目标；写入、屏幕输入和 MCP 等操作必须完整说“确认执行这项操作”，读取屏幕、窗口或工作区文件必须明确确认；长内容或疑似敏感参数需在桌面确认卡核对后点击允许或拒绝。应用会恢复最近的短期对话。点击语音键可手动进入连续对话；说完一句并停顿后，JARVIS 会自动识别、发送、语音回答，再继续聆听；再次点击结束。静音检测、语音识别和朗读均在本机执行，不录制或保存音频文件；只有识别文字会在对话轮次中发送给当前 Provider。缺少语音模型时，会先询问是否从 Apple 下载。快捷栏扬声器按钮控制普通文字对话的自动朗读；语音对话始终语音回答。朗读使用本机高品质中文语音，并微调语速、音高和句间停顿。首次启动前需完成 Phase 1 的模型配置或使用离线演示。

桌面快捷栏的“唤”和 `KWS` 按钮分别按需开启 Apple SpeechAnalyzer 和 Sherpa-ONNX 本机唤醒监听，应用启动时不会自动开启麦克风。监听短语为“贾维斯·零”；KWS 检测后会尝试把同句剩余语音交给本机识别。语音对话期间说“退下吧”会结束当前对话并恢复刚才选择的唤醒监听；唤醒识别异常时会按 1、2、4 秒间隔自动尝试恢复，连续失败三次后提示手动检查。需确认的操作会先播报目标：写入、屏幕输入和 MCP 等操作必须完整说“确认执行这项操作”，读取屏幕、窗口或工作区文件必须明确确认；长内容或疑似敏感参数需在桌面确认卡核对后点击允许或拒绝。首次启动应用时，macOS 会请求麦克风权限。监听复用 Apple 本机语音转写模型，音频仅在本机处理，不上传或保存；它不是专用低功耗关键词识别器，持续监听可能增加耗电并出现误识别。退出应用会停止监听。

登录后自动启动可通过 `scripts/install_autostart.command` 安装当前用户的 LaunchAgent；关闭时运行 `scripts/remove_autostart.command`。两个脚本只影响当前 macOS 用户。唤醒监听默认关闭；需要时点击对应按钮开启，再点击关闭或退出应用停止。

## 外部 MCP 工具（stdio）

可在 `config/config.yaml` 的 `mcp_servers` 中显式配置最多 8 个本机 MCP stdio 服务。示例结构如下，命令和参数由本机用户配置，不能由模型临时指定：

```yaml
mcp_servers:
  - name: example
    command: /absolute/path/to/mcp-server
    args: []
    env:
      ACCESS_TOKEN: ${EXAMPLE_MCP_TOKEN}
    timeout: 20
```

环境值使用 `${VARIABLE_NAME}` 时，从当前进程环境读取；其它值按字面传给服务。JARVIS 在启动时连接配置的服务并注册其工具；每次 MCP 工具调用都需要本机确认。外部服务以当前 macOS 用户身份运行，应只配置你信任的服务。当前支持 stdio 工具发现和调用，不支持远程 HTTP MCP、resources 或 prompts。CLI 与桌面常驻 Agent 生命周期内复用 MCP 连接。

## 重新安装

使用已安装的 Python 3.11+：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

虚拟环境绑定创建时使用的 Python 解释器；若该解释器被移除，需要用自己安装的 Python 3.11+ 重建 `.venv`。

`requirements-lock.txt` 记录本机测试时依赖版本。重现该依赖环境可先安装 lock 文件，再用 `pip install --no-deps -e .` 安装本项目。

## 之后配置真实模型

用户已选择先离线验收。需要真实模型时：

```bash
python -m app.main --setup
```

向导会在本机询问服务商、Base URL 和模型 ID，并通过不回显的输入提示收取 API Key；它会以仅当前用户可读写的权限创建 `.env`，拒绝覆盖已有 `.env`。密钥不用发到聊天里。OpenAI 地址默认 `https://api.openai.com/v1`，Ollama Cloud 默认 `https://ollama.com/v1`；豆包地址和模型 ID 使用你账户中的配置。模型必须支持 Chat Completions；Agent 工具调用还需要模型支持 function calling。

使用 Ollama Cloud 时，在 [Ollama 密钥设置](https://ollama.com/settings/keys)创建 API Key，再运行向导并选择 `ollama`。模型 ID 填 Ollama Cloud 中可用的模型名称；使用额度和模型可用性以 Ollama 账户为准。此方式调用云端服务，需要联网。完全本地运行则使用另一套本机 Ollama API 配置。

```bash
.venv/bin/python -m app.main --provider openai --once '你好，请简短介绍自己'
.venv/bin/python -m app.main --provider openai --once '调用工具查询当前时间'
```

使用豆包时将参数改为 `--provider doubao`，使用 Ollama 时改为 `--provider ollama`。模型名称不写死。环境变量优先于 `.env`；命令行 Provider 优先于环境变量和 YAML。缺失配置会明确报错并以状态码 2 退出，不偷偷切换到模拟成功。

## Phase 3 浏览器

首次使用浏览器工具前，在项目目录激活 `.venv` 后安装依赖和 Chromium：

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Agent 可调用 `browser_open` 打开公网 HTTP/HTTPS 标准端口页面，以及 `browser_read_page` 读取当前页面标题和最多 10,000 字符正文。两项操作每次都需要在 CLI 本机确认。浏览器请求会拦截本机、局域网和非 HTTP(S) 地址；页面正文视为不可信输入。当前为无头浏览器，不提供任意点击、表单提交、下载或文件上传能力。

## Phase 4 屏幕与输入

在项目目录激活 `.venv` 后安装 macOS 原生框架绑定：

```bash
python -m pip install -e '.[macos]'
```

重新启动 JARVIS 后，请求“检查 macOS 屏幕和辅助功能权限”。屏幕 OCR 和输入工具会检查权限状态，并告知缺少的权限。到 **系统设置 → 隐私与安全性 → 屏幕录制 / 辅助功能** 授权当前启动 JARVIS 的应用：桌面版为 `JARVIS Desktop Pet`，CLI 版为 `Terminal`。授权后完全退出并重新打开 JARVIS。工具不会自动弹出系统授权提示。

`read_screen_text` 读取主显示器并通过 macOS Vision OCR 返回文字及坐标；每次都需本机确认，识别文字会发给当前模型。新的辅助功能工具可检查当前应用窗口的控件树，再对刚检查到的控件执行按下、聚焦或填入普通文本；每次读取和操作仍需本机确认，并校验窗口控件标识。密码框不允许自动填入。`click_screen` 只支持用户确认后的单击；`type_screen_text` 限制为每次最多 500 字符；`press_screen_key` 只支持 Enter、Tab、Escape、删除、空格和方向键。所有输入动作均逐次确认。桌面版需在系统设置 → 隐私与安全性 → 辅助功能中为 `.build/JARVIS Voice.app` 授权。

## Phase 5 语音

首次使用 `/voice` 时，JARVIS 会用系统 Swift 编译器在项目的 `.build/JARVIS Voice.app` 生成语音辅助程序。录音由你输入 `/voice` 主动开始，看到录音提示后说话，再按回车停止；录音最长 30 秒。支持普通话（`/voice` 或 `/voice zh`）和美式英语（`/voice en`）。识别结果会显示在终端并作为普通用户消息发送给当前模型。录音只在内存缓冲，不保存音频文件；SpeechAnalyzer 使用 macOS 本机识别模型。如果模型尚未安装，首次使用会询问是否从 Apple 下载模型资源；只下载模型，不上传录音。拒绝下载时不会开始录音。

第一次使用时，macOS 会询问 **麦克风** 权限。通过 Terminal 启动时，系统设置中会显示 **Terminal**；请允许它访问麦克风。SpeechAnalyzer 本机转写不使用旧版 Siri 语音识别授权。项目使用 Swift 编译器（Xcode Command Line Tools）生成带有麦克风用途说明的辅助程序。

输入 `/speak` 可让 macOS `say` 朗读最近一条 JARVIS 回复；朗读不自动开始。语音能力不额外安装 Python 音频依赖。

OpenAI 适配器依据 [官方 Chat Completions 接口](https://developers.openai.com/api/reference/resources/chat)，并用于 Ollama Cloud 的 OpenAI 兼容接口。豆包适配器复用兼容协议，真实端点与账户功能尚未联调。`stream()` 支持文本 SSE；当前 CLI 的 Agent Loop 使用完整 `chat()` 响应处理结构化工具调用。

## 测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.main --provider mock --once '当前时间'
.venv/bin/python -m pip check
```

测试包含离线闭环、参数校验、确认拒绝、BLOCKED 禁止、错误重新决策、步数限制、超时、历史清理、HTTP 模拟传输、流响应与 CLI 子进程。HTTP 模拟测试不代表真实 API 已连通。

## Phase 2 工具与安全边界

首次确认使用文件或终端工具时会在本机创建 `~/JARVIS_Workspace`。文件工具固定限制于该目录：只接受相对路径，拒绝 `..`、绝对路径和符号链接组件；读取仅支持不超过 100 KB 的 UTF-8 普通文件，写入上限 100 KB、原子替换且权限为 600。设置文件中的 `workspace` 不能改到其他目录。目录列表、文件读取和写入都要求本机输入 `yes`，避免把本地文件名或内容未经确认交给模型。

应用工具只允许打开 Finder、Calculator、Notes、Safari 和 TextEdit，且每次需确认。终端工具只有 `python_version`、`node_version`、`git_status` 三项，工作目录固定为工作区根目录；使用固定可执行文件和参数数组，不经 Shell，不接受命令字符串、路径参数、管道、重定向或模型生成代码。终端调用每次需本机确认，确认结果会在 CLI 输出一条不含参数的 `[Audit]` 记录。拒绝确认、输入结束或无确认回调时均不执行。

工具风险由代码定义，模型无法修改。默认工具需确认；BLOCKED 不可执行；用户未明确确认则拒绝。事件日志不记录用户输入、工具参数、回复正文或密钥。网络连接失败最多重试三次；工具失败交回 Agent 决策，不自动重放有副作用的操作。

文件能力只访问 `~/JARVIS_Workspace`；终端能力是诊断命令白名单，不是通用 Shell。浏览器能力仅允许访问公网标准 HTTP(S) 地址。屏幕读取及鼠标键盘输入均需本机确认。

Phase 1 无需麦克风、屏幕录制或辅助功能权限。后续需要时再检查实际权限，并说明“系统设置 → 隐私与安全性”的具体授权项。

Phase 1 真实联调记录见 `docs/PHASE1_REPORT.md`；Phase 2 实现边界见 `docs/PHASE2_REPORT.md`；Phase 3 浏览器实现说明见 `docs/PHASE3_REPORT.md`；Phase 4 屏幕与输入说明见 `docs/PHASE4_REPORT.md`；Phase 5 语音说明见 `docs/PHASE5_REPORT.md`；Phase 6 记忆实现和隐私边界见 `docs/PHASE6_REPORT.md`；整体路线见 `docs/ARCHITECTURE.md`。
