# JARVIS：分阶段设计

项目根目录是当前目录，不额外嵌套 JARVIS 文件夹。用户文件工具的独立沙箱固定为 `~/JARVIS_Workspace`。

CLI → Agent → Provider 决策 → Registry 查找 → Executor 权限与参数检查 → Tool → 观测结果 → Provider 再决策。

模型通过结构化 function calling 选择工具；不解析模型输出中的 Shell，也不执行模型返回的代码。循环有步数限制，错误结果送回模型以便修正计划。确认只由本机用户产生，模型不能通过参数赋予自身权限。所有工具风险由代码定义。

Phase 2 文件访问使用相对路径及目录文件描述符逐组件打开，并拒绝符号链接；文件写入在工作区内通过临时文件原子替换。应用名和终端任务均使用枚举白名单。终端通过固定可执行文件和 argv 启动，工作目录固定为工作区根目录，禁止 Shell、自由参数和模型生成代码。目录列举/读取/写入、应用启动和终端调用均经本地确认；CLI 输出不含参数的确认审计结果。

Provider 提供 chat 和文本 stream；Agent 使用 chat 处理完整工具调用。OpenAI 与豆包使用显式配置的 OpenAI-compatible Chat Completions 端点；豆包真实账户的模型及功能兼容性留待联调。mock 仅用于确定性离线演示，不具备自然语言推理能力。

Phase 3 浏览器使用 Playwright Chromium；仅开放公网 HTTP/HTTPS 标准端口导航及当前页面正文读取。每次打开和读取均需要本机确认，拦截本机/局域网目标，页面内容按不可信数据处理。

Phase 4 使用 macOS Vision 对主显示器截图做本地 OCR，输出文字和点击坐标；截图和识别文字在本机确认后才会交给模型。Core Graphics 鼠标和键盘事件逐次确认，坐标限定在主显示器，按键使用白名单。屏幕录制和辅助功能状态由系统权限 API 检查，不在缺少权限时模拟操作。

Phase 5 通过带麦克风用途说明的 macOS 辅助 App 录制用户主动启动的短语音；AVAudioEngine 将音频缓冲送入 SpeechAnalyzer 与 SpeechTranscriber。本机识别模型通过 AssetInventory 检查；缺失时先征求用户同意，再从 Apple 下载模型资源。音频不写入磁盘或发送到网络。识别文字作为普通 CLI 消息交给 Agent。macOS `say` 仅在用户输入 `/speak` 后朗读最近回复。

状态通过事件总线发布，CLI 是订阅者，未来 UI 可替换订阅者。日志只记录事件类型，不记录输入、模型回复、工具参数或 API Key。Phase 6 使用本机 SQLite：短期记忆只存最近 N 轮的用户输入和最终助手回复；长期事实、任务标题及笔记只由用户通过 CLI 显式保存。恢复的短期历史和显式记忆会进入模型上下文，因此会发送给所选 Provider。数据库位于 `~/Library/Application Support/JARVIS/memory.sqlite3`，目录/文件权限为 700/600；内容是本机明文。`/reset` 只清短期，`/forget all` 清三类记忆；支持逐条删除长期及任务记忆。

后续阶段必须分别实现、测试、修复后再推进：

1. Phase 1：配置、Provider、Registry、Agent Loop、事件、CLI；真实模型普通对话及 current_time function calling 已联调并验收。
2. Phase 2：白名单应用启动、工作区文件读写和终端诊断白名单；工具与离线安全测试已完成，真实模型端到端调用待验收。
3. Phase 3：Playwright 浏览器；受限公网导航和页面文本读取已实现，本机依赖已安装，真实网页调用待验收。
4. Phase 4：屏幕 OCR、鼠标/键盘白名单输入；OCR 和权限检查已在用户 Mac 实测通过，鼠标/键盘输入尚待实测。
5. Phase 5：按键语音输入、本机 STT、按需 TTS；中文语音转写和 `/speak` 均已由用户实测成功。
6. Phase 6：SQLite 短期/长期/任务记忆。已实现 bounded 短期历史、显式长期记忆和任务笔记，提供 CLI 查询/删除/全部清除控制；自动化测试和用户本机体验均已通过。
7. Phase 7：桌面宠物。用户确认安装 Rust 后，已完成 Tauri 2/Vue 壳、透明置顶窗口、粒子人物、对话区、短期历史恢复、记忆管理、JSON Lines Python Agent bridge 和 UI 工具确认。桌面端现复用常驻 Python Agent/Provider/MCP 连接；持久桥接双请求测试已通过，UI 连续多轮仍待实测。连续语音闭环已在新 release `.app` 验收；唤醒词需用户主动开启并待实际麦克风验收。已实现空白透明区域点击穿透，底层应用收到点击仍待实测。独立运行时打包和发布签名待完成。
8. Phase 8：唤醒词。已加入默认关闭的“贾维斯·零”本机监听入口，复用 SpeechAnalyzer 转写并在本机匹配唤醒短语；触发后进入已有连续语音对话。它不是低功耗专用关键词模型，仍需在目标 Mac 实测耗电、误唤醒、权限和停止行为。
9. Phase 9：MCP。已加入配置驱动的本机 stdio MCP 客户端，可发现和调用 tools；所有 MCP 工具强制本机确认。远程 HTTP transport、resources/prompts 与 OAuth 仍未实现。

截至 2026-10-09：Phase 1 与 Phase 5 已完成端到端验收；Phase 2 和 Phase 3 已实现但真实调用待验收；Phase 4 的 OCR/权限检查通过、输入动作待验收；Phase 6 已实现、自动化测试通过且用户已验证；Phase 7 连续语音的实际收音、自动分句、模型回复、TTS 和停止流程已在桌面完成验收；点击穿透已实现但桌面下方应用的接收效果待验收；独立运行时打包、签名和透明合成目视验收仍待完成；唤醒词与 MCP 代码已接入但尚待本机实测。阶段编号表示路线顺序，不代表当前阶段的所有子能力都已验收。

Phase 1 无需系统隐私权限。不预建尚未实现的模块来假装功能完成。

## Phase 10–12 补充（2026-10-10）

Phase 10–11 增加 Sherpa-ONNX 中文/英文关键词检测 helper。桌面快捷栏 `KWS` 按钮按需启动该监听，`唤` 按钮使用 Apple SpeechAnalyzer 路径；默认不自动开启麦克风。用户曾在终端运行 KWS 候选脚本并确认检测到“贾维斯·零”。候选脚本的终端输出不等于桌面全链路或同句命令交接验收。模型只由 `scripts/setup_kws_model.py` 下载到本机 `.build/`，源码仓库不包含模型。

Phase 12 保留现有人物 PNG 和 UI 布局，按待机、监听、唤醒、思考和朗读状态应用轻微 CSS 动画，并遵从系统减少动态效果设置。人物素材是单张扁平 PNG，暂不具备独立口型或肢体动画。

发布边界：当前桌面 `.app`/`.dmg` 仍依赖工程根目录、Python 虚拟环境、`.env` 配置和本机语音模型/辅助资源，因此不应作为可直接复制安装的独立版本发布。仓库只应包含源码、锁文件、示例配置和不含密钥的文档；用户数据、API 凭据、模型、虚拟环境及构建目录必须排除。

API 依据：https://developers.openai.com/api/reference/resources/chat
