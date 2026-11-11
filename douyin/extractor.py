# -*- coding: utf-8 -*-
"""从抖音作品详情（aweme_detail）中提取视频下载地址与基础信息。

参考：MediaCrawler 的 ``media_platform/douyin/media.py``。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 视频清晰度字段，按优先级排列（h264 与 256 通常为无水印源）
_VIDEO_ADDR_KEYS = ("play_addr_h264", "play_addr_256", "play_addr")

# 封面字段，按优先级排列
_COVER_KEYS = ("raw_cover", "origin_cover", "cover", "dynamic_cover")


def _url_list_of(container) -> List[str]:
    """接口响应里同名字段可能是字符串或 None，统一收敛为 url 列表。"""
    if not isinstance(container, dict):
        return []
    return [url for url in (container.get("url_list") or []) if url and isinstance(url, str)]


def extract_video_urls(aweme_detail: Dict) -> List[str]:
    """提取视频地址候选列表。

    同一档清晰度会返回多个 CDN 地址，优先取 ``url_list`` 最后一个（通常无水印），
    其余作为备用；主地址不可用时依次降级到更低清晰度档位。
    """
    video_item = aweme_detail.get("video")
    if not isinstance(video_item, dict):
        return []

    for key in _VIDEO_ADDR_KEYS:
        candidates = _url_list_of(video_item.get(key))
        if candidates:
            return list(reversed(candidates))

    # 兜底：bit_rate 列表里码率最高的那一档
    bit_rates = [entry for entry in (video_item.get("bit_rate") or []) if isinstance(entry, dict)]
    for entry in sorted(bit_rates, key=lambda item: item.get("bit_rate", 0), reverse=True):
        candidates = _url_list_of(entry.get("play_addr"))
        if candidates:
            return list(reversed(candidates))

    return []


def extract_cover_url(aweme_detail: Dict) -> str:
    """提取视频封面地址。"""
    video_item = aweme_detail.get("video")
    if not isinstance(video_item, dict):
        return ""
    for key in _COVER_KEYS:
        candidates = _url_list_of(video_item.get(key))
        if candidates:
            return candidates[-1]
    return ""


def to_no_watermark(url: str) -> str:
    """将带水印地址中的 ``playwm`` 替换为无水印的 ``play``。"""
    return url.replace("playwm", "play") if url else url


def extract_video_info(aweme_detail: Dict) -> Dict[str, Any]:
    """提取视频下载链接与基础信息，返回结构化 dict。"""
    video_urls = extract_video_urls(aweme_detail)
    # 去水印 + 去重（保持顺序）
    no_watermark_urls = list(dict.fromkeys(to_no_watermark(u) for u in video_urls if u))

    video_item = aweme_detail.get("video") or {}
    author = aweme_detail.get("author") or {}

    return {
        "aweme_id": str(aweme_detail.get("aweme_id", "")),
        "title": aweme_detail.get("desc", ""),
        "author": author.get("nickname", ""),
        "cover": extract_cover_url(aweme_detail),
        "duration_ms": video_item.get("duration", 0),
        "video_url": no_watermark_urls[0] if no_watermark_urls else "",
        "video_urls": no_watermark_urls,
    }
