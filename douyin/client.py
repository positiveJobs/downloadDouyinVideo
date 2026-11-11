# -*- coding: utf-8 -*-
"""DouYinClient：组装反爬参数并调用抖音 Web 接口。

仅保留「按 aweme_id 获取视频详情」这一能力；评论、搜索、创作者相关接口均已移除。

参考：MediaCrawler 的 ``media_platform/douyin/client.py``。
"""
from __future__ import annotations

import base64
import copy
import urllib.parse
from typing import Any, Dict

import httpx

from .signer import get_a_bogus, get_web_id

# 抖音边缘网关 ArgusSecurityPlugin 要求该请求头；当前网关不校验取值，固定传 "1" 即可。
DOUYIN_ARGUS_HEADER_VALUE = "1"

_DETAIL_URI = "/aweme/v1/web/aweme/detail/"

# detail 接口的公共参数（浏览器指纹）。与参考实现保持一致。
COMMON_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "version_code": "190600",
    "version_name": "19.6.0",
    "update_version_code": "170400",
    "pc_client_type": "1",
    "cookie_enabled": "true",
    "browser_language": "zh-CN",
    "browser_platform": "MacIntel",
    "browser_name": "Chrome",
    "browser_version": "125.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "os_name": "Mac OS",
    "os_version": "10.15.7",
    "cpu_core_num": "8",
    "device_memory": "8",
    "engine_version": "109.0",
    "platform": "PC",
    "screen_width": "2560",
    "screen_height": "1440",
    "effective_type": "4g",
    "round_trip_time": "50",
}


def _abort_reason(response: "httpx.Response") -> str:
    """解码抖音边缘网关返回的风控中断原因（x-whale-throughput-abort-data）。"""
    raw = response.headers.get("x-whale-throughput-abort-data", "")
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return raw


class DataFetchError(Exception):
    """接口请求或响应解析异常。"""


class DouYinClient:
    """抖音 Web 接口客户端（视频详情）。"""

    def __init__(
        self,
        *,
        headers: Dict[str, str],
        cookie_dict: Dict[str, str],
        ms_token: str,
    ) -> None:
        self._host = "https://www.douyin.com"
        self.headers = headers
        self.cookie_dict = cookie_dict
        self.ms_token = ms_token

        # Argus 网关头 + uifid 头
        self.headers.setdefault("x-tt-argus", DOUYIN_ARGUS_HEADER_VALUE)
        uifid = cookie_dict.get("UIFID") or cookie_dict.get("UIFID_TEMP", "")
        if uifid:
            self.headers.setdefault("uifid", uifid)

    # ------------------------------------------------------------------
    # 参数组装与签名
    # ------------------------------------------------------------------
    def _build_query(self, uri: str, detail_params: Dict[str, Any]) -> str:
        """组装完整 query string（含 a_bogus）。

        签名时使用「不含 a_bogus」的 query string，最后再追加 a_bogus，
        两者使用同一套 ``urllib.parse.urlencode`` 编码，保证签名与服务端一致。
        """
        params: Dict[str, Any] = copy.deepcopy(detail_params)
        params.update(COMMON_PARAMS)
        # 每次请求随机生成 webid、使用当前上下文的 msToken
        params["webid"] = get_web_id()
        params["msToken"] = self.ms_token

        query_string = urllib.parse.urlencode(params)
        params["a_bogus"] = get_a_bogus(uri, query_string, self.headers["User-Agent"])
        return urllib.parse.urlencode(params)

    async def _get(self, uri: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
        query = self._build_query(uri, params)
        url = f"{self._host}{uri}?{query}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30)

        reason = _abort_reason(response)
        if response.status_code != 200:
            raise DataFetchError(
                f"接口返回状态码 {response.status_code}，响应: {response.text[:200]!r}"
                + (f"，风控原因: {reason}" if reason else "")
            )
        if response.text in ("", "blocked"):
            message = f"接口返回空响应（status={response.status_code}）"
            if reason:
                message += f"，风控原因: {reason}"
            message += "。抖音详情接口当前需要登录，请通过 --cookies 传入已登录 Cookie。"
            raise DataFetchError(message)
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            raise DataFetchError(f"响应不是合法 JSON：{response.text[:200]!r}") from exc

    # ------------------------------------------------------------------
    # 视频详情
    # ------------------------------------------------------------------
    async def get_video_by_id(self, aweme_id: str) -> Dict[str, Any]:
        """按 aweme_id 获取视频详情（aweme_detail）。

        Argus 风控要求 ``uifid`` 与 ``verifyFp/fp`` 成套出现：
        - ``uifid`` 用 UIFID（没有时退回 UIFID_TEMP）cookie；
        - ``verifyFp`` 与 ``fp`` 用 ``s_v_web_id`` cookie。
        """
        s_v_web_id = self.cookie_dict.get("s_v_web_id", "")
        params = {
            "aweme_id": aweme_id,
            "uifid": self.cookie_dict.get("UIFID") or self.cookie_dict.get("UIFID_TEMP", ""),
            "verifyFp": s_v_web_id,
            "fp": s_v_web_id,
        }

        headers = copy.deepcopy(self.headers)
        headers.pop("Origin", None)
        headers["Referer"] = f"https://www.douyin.com/video/{aweme_id}"

        result = await self._get(_DETAIL_URI, params, headers)
        return result.get("aweme_detail", {})
