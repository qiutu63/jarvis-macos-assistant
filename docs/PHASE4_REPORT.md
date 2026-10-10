# Phase 4 屏幕与输入能力实现记录

日期：2026-10-08（Asia/Shanghai）

## 已实现

- `check_macos_permissions`：读取当前 JARVIS 进程的屏幕录制及辅助功能事件权限状态，不主动弹出系统授权提示。桌面版需授权 `JARVIS Desktop Pet`；CLI 版需授权 `Terminal`。
- `read_screen_text`：经本机确认后截取主显示器，使用 macOS Vision 做本地 OCR，最多返回 80 个文字项及其屏幕坐标；截图临时文件会在结束时删除。
- `click_screen`：经确认后仅在主显示器范围内单击左键。
- `type_screen_text`：经确认后向当前焦点输入最多 500 个字符。
- `press_screen_key`：经确认后按固定白名单键盘键。
- `inspect_active_window`：使用 macOS Accessibility API 读取当前前台应用窗口中的可访问控件树；读取结果经确认后才发送给模型，并跳过密码框内容。
- `operate_ui_element`：用最近一次检查出的进程、窗口、控件路径及控件标签重新校验后，执行 press、focus 或最多 500 字符的普通文本输入；密码框不允许写入。
- 工具仅在 macOS 原生框架依赖可用及对应权限通过时工作；缺少权限时会提示设置路径，不执行输入事件。

## 本机启用与授权

在项目目录激活 `.venv` 后安装：

```bash
python -m pip install -e '.[macos]'
```

原记录曾注明本次自动安装请求未完成。**后续本机状态：依赖已可用。** 用户提供的实际终端记录显示 `read_screen_text` 已成功执行并返回文字与坐标，因此屏幕读取所需的运行环境已能工作。

在 JARVIS 中请求检查权限。需要时，在 **系统设置 → 隐私与安全性 → 屏幕录制 / 辅助功能** 中为当前启动 JARVIS 的应用授权：桌面版选择 `JARVIS Desktop Pet`，CLI 版选择 `Terminal`。授权后完全退出并重新打开 JARVIS。

## 限制及验收状态

视觉能力目前是本地 OCR 和坐标返回，不会把整张图像传给模型。所有屏幕读取及输入动作均要求本机逐次确认。

## 进度核对（2026-10-08）

- **实现状态：完成。** 屏幕读取、点击、文本输入、白名单按键和权限查询工具均在代码中注册。
- **屏幕读取实测：通过。** 用户提供的终端输出显示 `read_screen_text` 在本机确认后成功返回当前屏幕文字及坐标；此前出现的 Vision OCR `key does not exist` 和超时属于旧失败记录，后来已有成功结果。
- **权限状态：已授予。** 用户后续的权限查询输出为屏幕录制和辅助功能均已授权。
- **当前执行环境复核（2026-10-09）：** 本次 CLI 上下文读到 `screen_capture=true`、`input_control=false`；TCC 授权按启动应用区分，桌面应用的实际状态仍需在桌面版中调用 `check_macos_permissions` 确认。此前 CLI 权限结果不等同于桌面版权限。
- **鼠标/键盘输入实测：尚无可核对记录。** 当前对话未展示 `click_screen`、`type_screen_text` 或 `press_screen_key` 实际执行成功，因此这些交互仍待单独验收。
- **通用辅助功能接口：已接入原生 Swift helper，首次使用前需要给 `.build/JARVIS Voice.app` 授予辅助功能权限；本次本机查询值为 `accessibility=false`，因此尚未授权验收。**

因此，Phase 4 的屏幕 OCR 和权限检查已实测通过；输入操作的代码已实现，但尚不能按现有证据标为端到端验收完成。
