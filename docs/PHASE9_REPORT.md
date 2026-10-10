# Phase 9：外部 MCP 工具客户端

## 已实现

- `config/config.yaml` 可声明最多 8 个本机 stdio MCP 服务，指定可执行文件、参数、环境变量和超时。
- 启动时通过 JSON-RPC 初始化服务、读取工具清单，并将服务工具注册到现有 Agent 工具表。
- 工具名称加 `mcp_<server>__` 前缀；调用参数先按 MCP 输入 schema 的常用类型、必需字段、枚举、长度和数值范围检查。
- 每个外部 MCP 工具固定要求本机确认，并复用现有 Agent 循环和工具结果长度上限。
- MCP 服务环境采用显式白名单传递；配置中的 `${NAME}` 从本机进程环境读取。
- Python 自动化覆盖 stdio 握手、工具发现、参数校验、确认拒绝和确认后调用。

## 限制与待验收

- 当前只支持 stdio tools，不支持远程 HTTP transport、OAuth、resources、prompts 或 server-initiated sampling。
- CLI 在进程启动时连接并在退出时关闭 MCP 服务；桌面常驻 Agent 生命周期内复用 MCP 服务。
- MCP 服务在用户账户权限下运行。只应配置可信服务；工具确认控制模型触发的工具调用，不隔离 MCP 服务本身。
- 需要使用用户实际配置的 MCP 服务做兼容性验收，并继续扩展 JSON Schema 校验覆盖面。
