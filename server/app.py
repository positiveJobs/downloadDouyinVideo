# -*- coding: utf-8 -*-
"""FastAPI 应用：会话管理、视频解析、视频下载 / 预览代理。"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.schemas import ResolveRequest, SessionStartRequest
from server.session import SessionManager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# 仅允许代理这些域名的视频资源，避免被当成任意 URL 代理
_ALLOWED_HOST_SUFFIXES = (
    "douyin.com",
    "douyinvod.com",
    "snssdk.com",
    "amemv.com",
    "byteimg.com",
    "byteicdn.com",
    "pstatp.com",
    "ibytedapm.com",
    "douyinpic.com",
    "zjcdn.com",
    "volccdn.com",
)

# 拉取 CDN 视频时的请求头（Referer 用于绕过防盗链）
_MEDIA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    # 不要压缩：Range 请求与 Content-Length 校验都依赖原始字节
    "Accept-Encoding": "identity",
    "Referer": "https://www.douyin.com/",
}

manager = SessionManager()
router = APIRouter()


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (name or "").strip())
    name = name.strip().strip(".")
    return name[:120] or "douyin_video"


def _ensure_allowed(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    allowed = bool(host) and any(
        host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES
    )
    if not allowed:
        raise HTTPException(status_code=400, detail="不允许的下载地址域名")


# ----------------------------------------------------------------------
# 会话
# ----------------------------------------------------------------------
@router.get("/health")
def health() -> dict:
    return {"status": "ok", "node_available": shutil.which("node") is not None}


@router.get("/session")
def get_session() -> dict:
    return manager.snapshot()


@router.post("/session")
async def start_session(req: SessionStartRequest) -> dict:
    try:
        return await manager.start_session(req.cookie)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/session")
async def close_session() -> dict:
    return await manager.close_session()


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
@router.post("/resolve")
async def resolve(req: ResolveRequest) -> dict:
    try:
        return await manager.resolve(req.input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        # 会话未就绪 / Node.js 签名环境未装好
        detail = str(exc)
        if "Node.js" in detail or "node" in detail.lower():
            detail += "（Docker 环境请确认镜像已安装 Node.js，见 README「常见问题」）"
        raise HTTPException(status_code=409, detail=detail)
    except Exception as exc:  # noqa: BLE001
        # 详细异常（含文件路径、JS 报错栈）只记日志，对外返回通用文案
        logger.exception("视频解析失败")
        raise HTTPException(status_code=500, detail="解析失败，请查看服务日志了解详情")


# ----------------------------------------------------------------------
# 视频代理（下载 / 预览）
# ----------------------------------------------------------------------
async def _open_stream(
    url: str, extra_headers: Optional[Dict[str, str]] = None
) -> Tuple[httpx.AsyncClient, httpx.Response]:
    headers = dict(_MEDIA_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    # 抖音的 play 地址通常先 302 跳到 CDN，必须跟随重定向；
    # CDN 边缘节点偶发连接失败，最多重试 3 次（短暂退避）
    last_error = "未知错误"
    for attempt in range(3):
        client = httpx.AsyncClient(follow_redirects=True)
        try:
            request = client.build_request("GET", url, headers=headers, timeout=60)
            response = await client.send(request, stream=True)
        except Exception as exc:  # noqa: BLE001
            await client.aclose()
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
            break

        if response.status_code in (200, 206):
            # 重定向后的最终地址也要过白名单，避免借跳转绕过代理限制
            try:
                _ensure_allowed(str(response.url))
            except HTTPException:
                await response.aclose()
                await client.aclose()
                raise
            return client, response

        status = response.status_code
        await response.aclose()
        await client.aclose()
        last_error = f"HTTP {status}"
        if status in (429, 500, 502, 503, 504) and attempt < 2:
            await asyncio.sleep(0.4 * (attempt + 1))
            continue
        break

    raise HTTPException(
        status_code=502,
        detail=f"视频资源请求失败（{last_error}），地址可能已过期",
    )


def _iter_and_close(
    client: httpx.AsyncClient, response: httpx.Response
) -> AsyncIterator[bytes]:
    async def generator() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes(256 * 1024):
                if chunk:
                    yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return generator()


@router.get("/download")
async def download(
    url: str = Query(..., description="视频下载地址"),
    filename: str = Query("douyin_video", description="保存文件名"),
):
    """代理下载：带上 Referer 拉取视频，避免浏览器直接下载被 403。"""
    _ensure_allowed(url)
    client, response = await _open_stream(url)

    safe = _sanitize_filename(filename)
    if not safe.lower().endswith(".mp4"):
        safe += ".mp4"
    disposition = f"attachment; filename=\"video.mp4\"; filename*=UTF-8''{quote(safe)}"
    return StreamingResponse(
        _iter_and_close(client, response),
        media_type="video/mp4",
        headers={"Content-Disposition": disposition},
    )


@router.get("/stream")
async def stream(
    url: str = Query(..., description="视频地址"),
    range_header: Optional[str] = Header(default=None, alias="Range"),
):
    """在线预览：代理 CDN 并透传 Range，支持播放器拖动进度。"""
    _ensure_allowed(url)
    extra = {"Range": range_header} if range_header else None
    client, response = await _open_stream(url, extra)

    headers: Dict[str, str] = {}
    for name in ("content-length", "content-range", "accept-ranges"):
        value = response.headers.get(name)
        if value:
            headers[name] = value

    return StreamingResponse(
        _iter_and_close(client, response),
        status_code=response.status_code,
        media_type=response.headers.get("content-type") or "video/mp4",
        headers=headers,
    )


# ----------------------------------------------------------------------
# 应用装配
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # 关闭时释放浏览器资源
    await manager.close_session()


app = FastAPI(
    title="抖音视频解析 Web 服务",
    version="1.0.0",
    description="基于 Playwright，根据抖音视频链接 / ID 解析视频下载地址",
    lifespan=lifespan,
)

# 先注册 /api 路由，再挂载静态页面，保证 API 优先匹配
app.include_router(router, prefix="/api")

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
