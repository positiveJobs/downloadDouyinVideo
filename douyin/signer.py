# -*- coding: utf-8 -*-
"""a_bogus 反爬签名与随机参数生成。

a_bogus 是抖音 Web 接口的核心反爬签名参数，由 ``libs/douyin.js`` 逆向实现，
本项目通过 PyExecJS 调用该脚本（依赖本机 Node.js）。

参考：MediaCrawler 的 ``media_platform/douyin/help.py``。
"""
from __future__ import annotations

import random
from pathlib import Path

import execjs

_LIBS_DIR = Path(__file__).resolve().parent.parent / "libs"
_DOUYIN_JS = _LIBS_DIR / "douyin.js"

# msToken 字符集（与抖音页面生成规则一致）
_MS_TOKEN_ALPHABET = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789=_-"

# 惰性编译，避免在没有 Node.js 时仅导入模块就报错
_sign_obj = None


def _get_sign_obj():
    """惰性编译 douyin.js，仅在真正需要签名时才要求 Node.js 存在。"""
    global _sign_obj
    if _sign_obj is not None:
        return _sign_obj
    if not _DOUYIN_JS.exists():
        raise RuntimeError(f"缺少签名脚本：{_DOUYIN_JS}")
    try:
        _sign_obj = execjs.compile(_DOUYIN_JS.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "初始化 JS 签名环境失败，请确认已安装 Node.js 并加入 PATH（PyExecJS 依赖 JS 运行时）。"
        ) from exc
    return _sign_obj


def get_web_id() -> str:
    """生成随机 webid（19 位数字）。"""

    def _e(t):
        if t is not None:
            return str(t ^ (int(16 * random.random()) >> (t // 4)))
        return "".join(
            [
                str(int(1e7)),
                "-",
                str(int(1e3)),
                "-",
                str(int(4e3)),
                "-",
                str(int(8e3)),
                "-",
                str(int(1e11)),
            ]
        )

    web_id = "".join(_e(int(x)) if x in "018" else x for x in _e(None))
    return web_id.replace("-", "")[:19]


def get_ms_token(length: int = 176) -> str:
    """生成随机 msToken（当页面 localStorage 里没有 xmst 时兜底）。"""
    return "".join(random.choice(_MS_TOKEN_ALPHABET) for _ in range(length))


def get_a_bogus(url: str, query_string: str, user_agent: str) -> str:
    """生成 a_bogus 签名。

    :param url: 接口路径，如 ``/aweme/v1/web/aweme/detail/``
    :param query_string: 已 URL 编码、且**不含** a_bogus 的 query string
    :param user_agent: 与请求一致的 User-Agent
    """
    sign_name = "sign_reply" if "/reply" in url else "sign_datail"
    return _get_sign_obj().call(sign_name, query_string, user_agent)
