# -*- coding: utf-8 -*-
"""Playwright 驱动的抖音浏览器上下文。

流程：启动 Chromium → 注入反检测脚本 →（可选）注入 Cookie → 打开 douyin.com
→ （可选）等待扫码登录 → 提取 Cookie / localStorage / User-Agent
→ 用这些上下文组装 ``DouYinClient`` 去请求视频详情接口。

参考：MediaCrawler 的 ``media_platform/douyin/core.py``。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.async_api import Playwright

from .client import DouYinClient
from .signer import get_ms_token

_LIBS_DIR = Path(__file__).resolve().parent.parent / "libs"
_STEALTH_JS = _LIBS_DIR / "stealth.min.js"

INDEX_URL = "https://www.douyin.com"
COOKIE_URLS = [
    "https://douyin.com",
    "https://www.douyin.com",
    "https://creator.douyin.com",
    "https://douhot.douyin.com",
    "https://live.douyin.com",
]


class DouYinCrawler:
    """Playwright 抖音视频解析器。"""

    def __init__(self, playwright: Playwright) -> None:
        self._pw = playwright
        self.browser = None
        self.browser_context = None
        self.page = None
        self.client: Optional[DouYinClient] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(
        self,
        headless: bool = True,
        cookies: Optional[List[Dict]] = None,
        aweme_id: Optional[str] = None,
        wait_for_login: bool = False,
    ) -> "DouYinCrawler":
        """启动浏览器、打开抖音页面，并初始化 API 客户端。

        - ``cookies``：Playwright 格式的 cookie 列表（见 :mod:`douyin.cookie_utils`）。
        - ``aweme_id``：传入时先打开该视频页做「预热」，页面会写入真实 msToken。
        - ``wait_for_login``：无 Cookie 时等待用户扫码登录，登录后再构建客户端。
        """
        chromium = self._pw.chromium
        self.browser = await chromium.launch(headless=headless)
        self.browser_context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )

        # 反检测脚本（与参考实现一致）
        if _STEALTH_JS.exists():
            await self.browser_context.add_init_script(path=str(_STEALTH_JS))

        # 可选的登录 Cookie（用于需登录的视频）
        if cookies:
            await self._inject_cookies(cookies)

        self.page = await self.browser_context.new_page()

        login_required = wait_for_login and not cookies
        if login_required:
            # 登录流程打开首页，登录面板更容易弹出
            start_url = INDEX_URL
        else:
            start_url = f"{INDEX_URL}/video/{aweme_id}" if aweme_id else INDEX_URL
        await self.page.goto(start_url, wait_until="domcontentloaded")

        if login_required:
            if not await self.wait_until_logged_in():
                raise RuntimeError("等待扫码登录超时（未检测到登录状态）")

        # 等待页面脚本写入 msToken（xmst）与基础 Cookie
        await self._wait_for_session()
        await self.refresh_client()
        return self

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
            self.browser_context = None
            self.page = None

    # ------------------------------------------------------------------
    # 能力
    # ------------------------------------------------------------------
    async def get_aweme_detail(self, aweme_id: str) -> Dict:
        """获取视频详情（aweme_detail）。"""
        if self.client is None:
            raise RuntimeError("crawler 尚未调用 start()")
        return await self.client.get_video_by_id(aweme_id)

    async def warmup_for_video(self, aweme_id: str) -> None:
        """打开指定视频页做预热，取真实 msToken 后重建客户端。

        与命令行单次解析的行为一致：真实视频页才会写入 ``localStorage.xmst``。
        """
        if aweme_id and self.page is not None:
            try:
                await self.page.goto(
                    f"{INDEX_URL}/video/{aweme_id}", wait_until="domcontentloaded"
                )
            except Exception:  # noqa: BLE001
                pass
        await self._wait_for_session()
        await self.refresh_client()

    async def is_logged_in(self) -> bool:
        """检测当前浏览器上下文是否已登录。"""
        try:
            local_storage = await self.page.evaluate("() => window.localStorage")
            if local_storage.get("HasUserLogin", "") == "1":
                return True
        except Exception:  # noqa: BLE001
            pass

        try:
            cookies = await self.browser_context.cookies(urls=COOKIE_URLS)
        except Exception:  # noqa: BLE001
            return False
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        return (
            cookie_dict.get("LOGIN_STATUS") == "1"
            or bool(cookie_dict.get("sessionid"))
            or bool(cookie_dict.get("sid_tt"))
        )

    async def wait_until_logged_in(self, timeout_s: int = 300, poll_ms: int = 1000) -> bool:
        """轮询等待用户扫码登录，成功返回 True，超时返回 False。"""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if await self.is_logged_in():
                # 给页面一点时间把登录态相关 Cookie 写全
                await self.page.wait_for_timeout(1500)
                return True
            await self.page.wait_for_timeout(poll_ms)
        return False

    async def get_browser_cookies(self) -> List[Dict]:
        """导出当前浏览器上下文的 Cookie（Playwright 格式），用于本地保存。"""
        if self.browser_context is None:
            return []
        return await self.browser_context.cookies(urls=COOKIE_URLS)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    async def _wait_for_session(self, timeout_ms: int = 8000) -> None:
        """轮询等待页面写入 localStorage 的 msToken（``xmst``），超时则继续（后面用随机值兜底）。"""
        waited = 0
        while waited < timeout_ms:
            try:
                local_storage = await self.page.evaluate("() => window.localStorage")
            except Exception:  # noqa: BLE001
                local_storage = {}
            if local_storage.get("xmst"):
                return
            await self.page.wait_for_timeout(500)
            waited += 500

    async def refresh_client(self) -> None:
        """从当前浏览器上下文重新提取 Cookie / localStorage / UA，重建 API 客户端。"""
        cookie_str, cookie_dict = await self._context_cookies()
        local_storage = await self.page.evaluate("() => window.localStorage")
        user_agent = await self.page.evaluate("() => navigator.userAgent")
        # 优先用页面生成的 msToken，缺失时兜底随机生成
        ms_token = local_storage.get("xmst") or get_ms_token()

        self.client = DouYinClient(
            headers={
                "User-Agent": user_agent,
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            cookie_dict=cookie_dict,
            ms_token=ms_token,
        )

    async def _context_cookies(self) -> Tuple[str, Dict[str, str]]:
        cookies = await self.browser_context.cookies(urls=COOKIE_URLS)
        cookie_str = ";".join(f"{c['name']}={c['value']}" for c in cookies)
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        return cookie_str, cookie_dict

    async def _inject_cookies(self, cookies: List[Dict]) -> None:
        await self.browser_context.add_cookies(cookies)
