"""Small, confirmation-gated Playwright browser tools."""
import ipaddress
import socket
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.permissions.policy import Risk
from app.tools.base import NoArguments, Tool


class OpenPageArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


def _public_web_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("网页地址格式无效") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
            or parsed.password or port not in (None, 80, 443)):
        raise ValueError("仅允许无凭据的 HTTP/HTTPS 公网页面（标准端口）")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("不允许访问本机或局域网地址")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)}
        except OSError as exc:
            raise ValueError("无法解析网页主机名") from exc
    blocked = sorted(str(address) for address in addresses if not address.is_global)
    if not addresses or blocked:
        resolved = f"（DNS 返回：{', '.join(blocked)}）" if blocked else ""
        raise ValueError(f"网页域名解析到非公网地址{resolved}，已被浏览器安全规则拦截；请检查当前网络的 DNS 或代理设置")
    return url


class BrowserSession:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None

    async def _ensure_page(self):
        if self._page is not None and not self._page.is_closed():
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("浏览器依赖未安装；请安装项目的 browser 可选依赖并运行 playwright install chromium") from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        context = await self._browser.new_context(java_script_enabled=True, accept_downloads=False)
        await context.route("**/*", self._guard_request)
        self._page = await context.new_page()
        self._page.set_default_navigation_timeout(8_000)
        self._page.set_default_timeout(8_000)
        return self._page

    @staticmethod
    async def _guard_request(route):
        try:
            _public_web_url(route.request.url)
        except ValueError:
            await route.abort()
            return
        await route.continue_()

    async def open(self, url: str) -> dict:
        try:
            url = _public_web_url(url)
            page = await self._ensure_page()
            response = await page.goto(url, wait_until="domcontentloaded")
            return {"url": page.url, "title": await page.title(),
                    "status": response.status if response is not None else None}
        except ValueError as error:
            return {"ok": False, "error": "blocked_by_network_policy", "detail": str(error)}
        except Exception:
            return {"ok": False, "error": "navigation_failed",
                    "detail": "网页未能加载。请检查网络连接、DNS 或代理设置。"}

    async def read(self) -> dict:
        try:
            page = await self._ensure_page()
            if not page.url or page.url == "about:blank":
                return {"ok": False, "error": "no_active_page", "detail": "当前没有成功打开的网页。"}
            text = await page.locator("body").inner_text(timeout=8_000)
            return {"url": page.url, "title": await page.title(), "text": text[:10_000]}
        except Exception:
            return {"ok": False, "error": "page_read_failed", "detail": "页面文字读取失败；请先确认网页已成功打开。"}

    async def close(self):
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = self._browser = self._playwright = None


_session = BrowserSession()


async def close_browser():
    await _session.close()


def browser_tools() -> list[Tool]:
    return [
        Tool("browser_open", "在受限 Playwright 浏览器中打开公网 HTTP/HTTPS 网页", OpenPageArguments,
             _session.open, Risk.CONFIRM),
        Tool("browser_read_page", "读取当前网页标题和正文文字（最多 10,000 字符）", NoArguments,
             _session.read, Risk.CONFIRM),
    ]
