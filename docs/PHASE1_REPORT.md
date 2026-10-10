# Phase 1 离线验收记录

日期：2026-09-28（Asia/Shanghai）

## 环境检查

- macOS 27.0 / arm64。
- 系统 Python 3.9.6 不符合要求；复用本机 Codex 已有 Python 3.12.14 创建项目 `.venv`。
- Node.js v24.21.0，npm 已存在。
- Git 2.54.0（Apple Git-157）。
- Xcode Command Line Tools：`/Library/Developer/CommandLineTools`。
- PATH 中未找到 rustc/cargo；Tauri 完整构建环境尚不具备。未下载 Rust 或其他新语言，后续下载先询问用户。
- Python 依赖已安装在 `.venv`，未修改系统 Python。

## 已验证

1. 第一批 Provider/Registry 基础测试：5 passed。
2. 接入 Agent/权限/事件后：16 passed。
3. 最初最终离线测试：24 passed；加入本机交互配置向导后，最终回归测试为 28 passed。
4. `python -m app.main --provider mock --once '当前时间'` 实际运行成功，查询到本机带时区时间；状态顺序为 Thinking → Planning → Executing → Observing → Planning → Completed。
5. `scripts/start.command --provider mock --once '你好'` 实际运行成功。
6. `pip check`：No broken requirements found。
7. `compileall -q app`：通过。

## 本地模型配置入口

新增 `python -m app.main --setup`，可在本机选择 OpenAI 或豆包，API Key 使用不回显输入，以原子写入方式保存为权限 600 的 `.env`，并拒绝覆盖既有密钥文件。向导通过离线测试验证，尚未使用真实账户端点。

## 明确未验证

用户选择“先完成离线测试，稍后配置模型”。因此没有调用真实模型 API；正常模型对话、真实 function calling、豆包端点兼容性仍待配置后验收。自动化中的 HTTP 使用模拟传输，不把这些测试记作真实联网成功。

Safari、VS Code、文件创建、电脑信息、AI 新闻等六项端到端任务涉及后续阶段，本轮未实现也未宣称通过。

当前没有桌面 UI、语音或电脑控制，不需要新增 macOS 隐私权限。

## 阶段结论

本报告记录 2026-09-28 当时的离线验收状态。之后已完成 Ollama Cloud 真实联调：普通对话和 `current_time` function calling 均成功；该结果由后续开发任务确认。Phase 1 已验收，并于 2026-10-08 开始 Phase 2。
