# -*- coding: utf-8 -*-
"""把用户输入（视频链接 / 短链 / 纯 ID）解析为抖音视频 aweme_id。

参考：MediaCrawler 的 ``media_platform/douyin/help.py`` 中的
``parse_video_info_from_url``，以及 ``client.py`` 中的 ``resolve_short_url``。
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

import httpx

# 匹配 /video/{id}、/note/{id}、modal_id={id}
_AWEME_ID_RE = re.compile(r"(?:/video/|/note/|modal_id=)(\d{5,25})")

# 短链 302 跳转的目标只允许跳到这些域（防止被指成任意内网地址）
_ALLOWED_REDIRECT_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com", "snssdk.com")


def _host_allowed(raw_url: str) -> bool:
    host = (urllib.parse.urlparse(raw_url).hostname or "").lower()
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _ALLOWED_REDIRECT_HOST_SUFFIXES
    )


@dataclass
class VideoUrlInfo:
    """抖音视频链接解析结果。"""

    aweme_id: str
    url_type: str = "normal"  # normal | short | modal


def parse_video_info_from_url(raw: str) -> VideoUrlInfo:
    """解析视频链接或 ID，返回 aweme_id。

    支持：纯数字 ID、``/video/{id}``、``/note/{id}``、``modal_id=`` 参数、
    以及 ``v.douyin.com`` 短链（短链需再由 :func:`resolve_short_url` 解析）。
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("输入为空，请提供抖音视频链接或 ID。")

    if raw.isdigit():
        return VideoUrlInfo(aweme_id=raw, url_type="normal")

    # 短链交给 resolve_short_url 处理
    if "v.douyin.com" in raw:
        return VideoUrlInfo(aweme_id="", url_type="short")

    # modal_id 参数（例如用户主页 / 搜索结果页里的 ?modal_id=xxx）
    query = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
    modal_id = query.get("modal_id", [""])[0]
    if modal_id.isdigit():
        return VideoUrlInfo(aweme_id=modal_id, url_type="modal")

    # /video/{id} 或 /note/{id}
    match = _AWEME_ID_RE.search(raw)
    if match:
        return VideoUrlInfo(aweme_id=match.group(1), url_type="normal")

    raise ValueError(f"无法从输入中解析出视频 ID：{raw}")


async def resolve_short_url(short_url: str) -> str:
    """解析 ``v.douyin.com`` 短链，返回真实 URL 或 aweme_id（失败时返回空串）。

    返回的字符串可以直接再交给 :func:`parse_video_info_from_url` 处理。
    """
    # 1) 优先取 30x 跳转的 Location 头
    async with httpx.AsyncClient(follow_redirects=False) as client:
        resp = await client.get(short_url, timeout=10)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            # 跳转目标必须仍在白名单域内，防止短链被利用成 SSRF 探针
            if location and _host_allowed(location):
                return location

    # 2) 兜底：跟随跳转，从最终 URL 里提取 aweme_id
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(short_url, timeout=10)
        match = _AWEME_ID_RE.search(str(resp.url))
        if match and _host_allowed(str(resp.url)):
            return match.group(1)

    return ""
