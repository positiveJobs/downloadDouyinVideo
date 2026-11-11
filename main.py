# -*- coding: utf-8 -*-
"""命令行入口：根据抖音视频链接 / 短链 / 纯 ID 解析视频下载链接。

用法示例：
    python main.py https://www.douyin.com/video/7525082444551310602
    python main.py 7525082444551310602
    python main.py https://v.douyin.com/xxxxxxx/

输出为 JSON，其中 ``video_url`` 为主下载地址（已去水印），
``video_urls`` 为按优先级排列的全部候选地址。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Optional

from playwright.async_api import async_playwright

from config import resolve_headless
from douyin.cookie_utils import parse_cookie_input
from douyin.crawler import DouYinCrawler
from douyin.extractor import extract_video_info
from douyin.parser import parse_video_info_from_url, resolve_short_url


async def resolve_video(raw_input: str, headless: bool, cookies: Optional[list]) -> dict:
    """解析输入并返回视频信息（含下载链接）。"""
    # 1) 解析 aweme_id（短链先跟随跳转）
    info = parse_video_info_from_url(raw_input)
    if info.url_type == "short":
        resolved = await resolve_short_url(raw_input)
        if not resolved:
            raise ValueError("短链解析失败，请检查链接是否有效。")
        info = parse_video_info_from_url(resolved)
    aweme_id = info.aweme_id

    # 2) 启动 Playwright，获取浏览器上下文并请求视频详情
    async with async_playwright() as playwright:
        crawler = DouYinCrawler(playwright)
        await crawler.start(headless=headless, cookies=cookies, aweme_id=aweme_id)
        try:
            aweme_detail = await crawler.get_aweme_detail(aweme_id)
        finally:
            await crawler.close()

    if not aweme_detail:
        raise ValueError(
            f"未获取到视频详情（ID: {aweme_id}）。可能原因：视频已删除、需登录，或账号被风控。"
        )

    # 3) 提取视频下载链接
    return extract_video_info(aweme_detail)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="根据抖音视频链接 / 短链 / 纯 ID 解析视频下载链接（基于 Playwright）。"
    )
    parser.add_argument("input", help="抖音视频链接、短链（v.douyin.com/xxx）或纯数字 ID")
    parser.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="使用有头（可见窗口）浏览器运行（覆盖 HEADLESS 环境变量）",
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="使用无头浏览器运行（覆盖 HEADLESS 环境变量）",
    )
    parser.set_defaults(headless=None)
    parser.add_argument(
        "--cookies",
        default="",
        help="已登录 Cookie，支持 Cookie-Editor 导出的 JSON 数组，或 k1=v1; k2=v2 字符串；"
        "也可通过环境变量 DOUYIN_COOKIES 提供",
    )
    args = parser.parse_args()

    cookie_input = args.cookies or os.environ.get("DOUYIN_COOKIES", "")
    try:
        cookies = parse_cookie_input(cookie_input) if cookie_input else []
    except ValueError as exc:
        print(f"[错误] Cookie 解析失败：{exc}", file=sys.stderr)
        sys.exit(1)

    headless = args.headless if args.headless is not None else resolve_headless()

    try:
        result = asyncio.run(
            resolve_video(
                args.input.strip(),
                headless=headless,
                cookies=cookies or None,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
