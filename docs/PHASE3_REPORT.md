# Phase 3 浏览器能力实现记录

日期：2026-10-08（Asia/Shanghai）

## 已实现

- 注册 `browser_open` 和 `browser_read_page` 两个 Playwright 工具，均要求 CLI 本机输入 `yes`。
- 打开公网 HTTP/HTTPS 标准端口页面，并返回最终 URL、标题和状态码。
- 读取当前页面正文，最多返回 10,000 字符。
- 拦截非 HTTP(S)、本机/局域网目标和非标准端口请求；禁用下载。
- 在 CLI 退出时关闭 Playwright 浏览器。
- Playwright 作为可选依赖，避免影响没有安装浏览器运行时的基础功能。

## 本机启用

在项目目录激活 `.venv` 后运行：

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

## 当前限制及验收状态

浏览器以无头模式运行，不提供任意点击、表单提交、下载或文件上传。网页内容作为不可信数据处理。Playwright 与 Chromium 已安装到当前本机环境；重启 CLI 后仍需实际进行一次网页操作，确认本机配置的真实模型能正确选择工具。

## 进度核对（2026-10-08）

- **实现状态：完成。** `browser_open`、`browser_read_page` 仍已注册，均要求本机确认；公网目标限制和页面正文长度限制由浏览器工具实现。
- **依赖状态：本机已安装。** 依据本报告原有记录，Playwright 与 Chromium 已安装。
- **真实模型端到端验收：尚无可核对记录。** 当前提供的终端记录没有展示通过 JARVIS 真实调用浏览器并读取页面的结果；仍需一次本机确认后的打开与读取操作，才能补记为实测通过。

本阶段的代码实现和依赖准备不等于浏览器端到端验收完成。
