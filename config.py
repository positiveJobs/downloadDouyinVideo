# -*- coding: utf-8 -*-
"""应用配置：加载 ``.env`` 并读取运行参数。"""
from __future__ import annotations

import os

from dotenv import load_dotenv

# 加载项目根目录下的 .env（已存在的同名环境变量优先，不会被覆盖）
load_dotenv()


def resolve_headless() -> bool:
    """返回是否以无头模式运行浏览器。

    ``HEADLESS`` 环境变量（布尔语义，与通用习惯一致）：

    - ``HEADLESS=true``  → 无头模式（默认，不显示窗口）；
    - ``HEADLESS=false`` → 有头模式（显示浏览器窗口）；
    - 未设置            → 无头模式。
    """
    raw = (os.environ.get("HEADLESS") or "").strip().lower()
    return raw not in ("false", "0", "no", "off")
