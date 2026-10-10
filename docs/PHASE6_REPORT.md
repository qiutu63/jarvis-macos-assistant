# Phase 6：SQLite 短期、长期和任务记忆

日期：2026-10-08（Asia/Shanghai）

## 数据范围与隐私

- 数据库固定默认在 `~/Library/Application Support/JARVIS/memory.sqlite3`；应用目录权限 700，数据库权限 600。拒绝数据库或其直接父目录为符号链接的情况。测试/本地运行可通过 `JARVIS_MEMORY_PATH` 覆盖路径。
- 短期记忆每轮仅存用户原始输入和最终助手回复，不持久化工具调用参数、工具输出或中间推理文本；默认保留最近 `history_turns` 轮（默认 8）。跨会话恢复后以普通 user/assistant 对话提供给模型。
- 长期记忆是用户明确保存的文本事实；任务记忆是用户明确保存的标题和笔记。不会自动从对话提取或保存。
- 本地 SQLite 内容不加密。被恢复或作为记忆上下文注入的内容会发送给当前配置的模型 Provider。删除控制：`/reset` 清短期，`/forget ID` 删除长期条目，`/task delete ID` 删除任务，`/forget all` 清除全部；也可删除数据库文件。
- `JARVIS_MEMORY_PATH` 是路径覆盖环境变量，适合测试隔离和本机数据管理；避免指向同步/共享目录，除非用户主动选择。

## CLI

- `/memory` 查看三类记忆的数量。
- `/reset` 清空短期历史。
- `/remember 文本`、`/memories`、`/forget ID` 管理长期事实。
- `/task save 标题 | 笔记`、`/tasks`、`/task delete ID` 管理任务记忆。
- `/forget all` 清除短期、长期和任务记忆。

长期记忆和任务笔记会以独立系统上下文注入，并明确标记为用户保存的数据而非指令。短期持久化历史不包含工具消息；当前运行期内 Agent 仍保留完整轮次以维持工具调用对话格式。

## 验证

- `.venv/bin/python -m pytest -q`：34 passed。
- 覆盖短期轮数上限、跨实例恢复、文件权限、逐条删除、短期清理、显式记忆注入及 CLI 全流程。
- 此报告记录的是本地自动化验证；真实模型对话中注入的体验尚未做在线验收。
