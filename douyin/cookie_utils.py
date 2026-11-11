# -*- coding: utf-8 -*-
"""Cookie 解析工具。

支持两种输入格式：
1. **Cookie-Editor 导出的 JSON**（浏览器插件 Cookie-Editor → Export → JSON），
   形如 ``[{"name": "...", "value": "...", "domain": ".douyin.com", ...}, ...]``；
2. **字符串形式**，形如 ``k1=v1; k2=v2``。

解析结果统一为 Playwright ``browser_context.add_cookies`` 可用的字典列表。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib.parse import urlparse

DEFAULT_DOMAIN = ".douyin.com"
DEFAULT_PATH = "/"

# Cookie 只允许注入抖音相关域名，防止通过 JSON 的 domain 字段写向其他站点
_ALLOWED_COOKIE_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com", "snssdk.com")


def _cookie_domain_allowed(domain: str) -> bool:
    host = (urlparse(domain).hostname or domain).lower().lstrip(".")
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in _ALLOWED_COOKIE_HOST_SUFFIXES
    )

# Cookie-Editor 的 sameSite 取值 -> Playwright 取值
_TO_PLAYWRIGHT_SAMESITE = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "Lax",
    "": "Lax",
}

# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def parse_cookie_input(raw: str) -> List[Dict[str, Any]]:
    """解析 Cookie 输入，返回 Playwright 格式的 cookie 字典列表。

    自动识别 Cookie-Editor JSON 与 ``k=v; k2=v2`` 字符串；空输入返回空列表。
    无法解析时抛出 ``ValueError``。
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    if raw[0] in "[{":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            return _parse_json_cookies(data)

    return _parse_cookie_string(raw)


def _parse_json_cookies(data: Any) -> List[Dict[str, Any]]:
    # 兼容 {"cookies": [...]} 与直接数组两种导出结构
    if isinstance(data, dict):
        data = data.get("cookies") or data.get("cookie_list") or []
    if not isinstance(data, list):
        raise ValueError("Cookie JSON 格式不正确：应为数组或包含 cookies 数组的对象")

    cookies: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue

        domain = item.get("domain") or DEFAULT_DOMAIN
        # domain 字段不可信：不是抖音域名就丢弃这条（字符串形式没有 domain，不受影响）
        if not _cookie_domain_allowed(str(domain)):
            continue

        cookie: Dict[str, Any] = {
            "name": str(name),
            "value": str(value),
            "domain": domain,
            "path": item.get("path") or DEFAULT_PATH,
        }

        expires = item.get("expirationDate", item.get("expires"))
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)
        if "httpOnly" in item:
            cookie["httpOnly"] = bool(item["httpOnly"])
        if "secure" in item:
            cookie["secure"] = bool(item["secure"])

        same_site = item.get("sameSite")
        if same_site:
            mapped = _TO_PLAYWRIGHT_SAMESITE.get(str(same_site).lower(), "Lax")
            cookie["sameSite"] = mapped
            # Playwright 要求 sameSite=None 时必须 secure
            if mapped == "None":
                cookie["secure"] = True

        cookies.append(cookie)

    if not cookies:
        raise ValueError("未从 Cookie JSON 中解析到有效条目（需要 name / value 字段）")
    return cookies


def _parse_cookie_string(raw: str) -> List[Dict[str, Any]]:
    cookies: List[Dict[str, Any]] = []
    seen = set()
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cookies.append(
            {
                "name": name,
                "value": value.strip(),
                "domain": DEFAULT_DOMAIN,
                "path": DEFAULT_PATH,
            }
        )

    if not cookies:
        raise ValueError("未从 Cookie 字符串中解析到有效条目（应为 k1=v1; k2=v2 形式）")
    return cookies
