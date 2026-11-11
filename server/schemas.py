# -*- coding: utf-8 -*-
"""请求 / 响应数据模型。"""
from pydantic import BaseModel, Field


class SessionStartRequest(BaseModel):
    cookie: str = Field(default="", description="Cookie-Editor JSON 或 k=v; k2=v2 字符串")


class ResolveRequest(BaseModel):
    input: str = Field(..., min_length=1, description="抖音视频链接、短链或视频 ID")
