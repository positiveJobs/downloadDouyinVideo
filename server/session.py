# -*- coding: utf-8 -*-
"""Playwright 会话管理。

同一时刻只维护一个浏览器会话（本地单用户场景）：

- 传入 Cookie：注入后直接进入 ``ready``（默认无头模式，由 ``HEADLESS`` 环境变量控制）；
- Cookie 为空：拒绝启动，由前端提示用户先填写 Cookie。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from config import resolve_headless
from douyin.cookie_utils import parse_cookie_input
from douyin.crawler import DouYinCrawler
from douyin.extractor import extract_video_info
from douyin.parser import parse_video_info_from_url, resolve_short_url

# 状态机：idle -> launching -> ready / error
STATUS_IDLE = "idle"
STATUS_LAUNCHING = "launching"
STATUS_READY = "ready"
STATUS_ERROR = "error"


class SessionManager:
    """管理 Playwright 浏览器会话的生命周期。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._resolve_lock = asyncio.Lock()  # 同一时刻只允许一次解析（共用同一个 page）
        self._pw = None
        self._crawler: Optional[DouYinCrawler] = None
        self._task: Optional[asyncio.Task] = None

        self.status = STATUS_IDLE
        self.mode = "headless"
        self.message = "尚未启动会话"
        self.error = ""
        self.logged_in = False

    # ------------------------------------------------------------------
    # 对外状态
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "message": self.message,
            "error": self.error,
            "logged_in": self.logged_in,
        }

    # ------------------------------------------------------------------
    # 启动 / 关闭
    # ------------------------------------------------------------------
    async def start_session(self, cookie_raw: str) -> Dict[str, Any]:
        """启动新会话（会先关闭旧会话）。Cookie 为空时抛出 ValueError。"""
        async with self._lock:
            await self._cancel_task_locked()
            await self._cleanup_locked()

            cookies = parse_cookie_input(cookie_raw)  # 可能抛 ValueError
            if not cookies:
                raise ValueError("Cookie 为空：请先填写有效的 Cookie 后再启动会话。")

            headless = resolve_headless()
            self.mode = "headless" if headless else "headed"
            self.status = STATUS_LAUNCHING
            self.error = ""
            self.message = "正在启动浏览器..."
            self._task = asyncio.create_task(self._bootstrap(cookies, headless))
            return self.snapshot()

    async def _bootstrap(self, cookies: List[Dict], headless: bool) -> None:
        try:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._crawler = DouYinCrawler(self._pw)
            self.message = (
                f"正在启动浏览器并预热会话（{'无头' if headless else '有头'}模式）..."
            )
            await self._crawler.start(headless=headless, cookies=cookies)
            self.logged_in = await self._crawler.is_logged_in()
            self.status = STATUS_READY
            self.message = "会话就绪，可以开始解析视频了。"
        except asyncio.CancelledError:
            self.logged_in = False
            self.status = STATUS_IDLE
            self.message = "会话已取消"
            raise
        except Exception as exc:  # noqa: BLE001
            self.logged_in = False
            self.status = STATUS_ERROR
            self.error = str(exc)
            self.message = f"会话启动失败：{exc}"
            await self._cleanup_locked()

    async def close_session(self) -> Dict[str, Any]:
        async with self._lock:
            await self._cancel_task_locked()
            await self._cleanup_locked()
            self.status = STATUS_IDLE
            self.mode = "headless"
            self.message = "会话已关闭"
            self.error = ""
            self.logged_in = False
            return self.snapshot()

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    async def resolve(self, raw_input: str) -> Dict[str, Any]:
        # 同一个 page 不能并发操作：排队执行，后来的请求等前一个完成
        async with self._resolve_lock:
            if self.status != STATUS_READY or self._crawler is None:
                raise RuntimeError("会话未就绪，请先启动会话")

            info = parse_video_info_from_url(raw_input)
            if info.url_type == "short":
                resolved = await resolve_short_url(raw_input)
                if not resolved:
                    raise ValueError("短链解析失败，请检查链接是否有效")
                info = parse_video_info_from_url(resolved)
            aweme_id = info.aweme_id

            # 打开视频页预热，取真实 msToken（与命令行行为一致）
            await self._crawler.warmup_for_video(aweme_id)
            detail = await self._crawler.get_aweme_detail(aweme_id)
            if not detail:
                raise ValueError(
                    f"未获取到视频详情（ID: {aweme_id}），可能已删除或需要登录"
                )
            return extract_video_info(detail)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    async def _cancel_task_locked(self) -> None:
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass

    async def _cleanup_locked(self) -> None:
        if self._crawler is not None:
            try:
                await self._crawler.close()
            except Exception:  # noqa: BLE001
                pass
            self._crawler = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None
