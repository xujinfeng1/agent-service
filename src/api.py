"""Agent Service —— AI 对话 + 工具调用 + 流式输出"""
import json
import uuid
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agent import agent
from src.tools import registry
from src.memory import memory
from src.config import config

# 注册工具
import src.cdp_tools  # noqa: F401
import src.builtin_tools  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-service")

app = FastAPI(
    title="Agent Service",
    description="AI Agent —— 对话、工具调用、流式输出",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 数据模型 ==========

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: str = Field(default="", description="会话 ID")
    system_prompt: str = Field(default="", description="系统提示词")
    stream: bool = Field(default=False, description="是否流式输出")
    model: str = Field(default="", description="指定模型")
    think_mode: bool = Field(default=False, description="DeepSeek 思考模式")


# ========== API 路由 ==========

@app.get("/")
async def root():
    return {
        "name": "Agent Service",
        "version": "1.0.0",
        "endpoints": {
            "chat": "POST /api/chat",
            "stream": "POST /api/chat (stream=true)",
            "tools": "GET /api/tools",
            "sessions": "GET /api/sessions",
            "health": "GET /api/health",
            "demo": "GET /demo",
        },
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": config.model, "tools_count": len(registry._tools)}


@app.get("/api/models")
async def list_models():
    return {"models": [
        {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "desc": "快速推理，支持思考模式"},
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "desc": "旗舰模型，支持思考模式"},
        {"id": "deepseek-reasoner", "name": "DeepSeek R1", "desc": "深度推理"},
    ], "current": config.model}


@app.post("/api/chat", response_model=None)
async def chat(req: ChatRequest):
    """核心对话接口"""
    session_id = req.session_id or str(uuid.uuid4())[:8]

    if req.stream:
        async def stream_generator():
            try:
                gen = await agent.chat(
                    session_id=session_id,
                    user_message=req.message,
                    system_prompt=req.system_prompt,
                    stream=True,
                    model_override=req.model or None,
                    think_mode=req.think_mode,
                )
                async for chunk in gen:
                    yield chunk
            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                yield json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False) + "\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "X-Session-Id": session_id,
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    result = await agent.chat(
        session_id=session_id,
        user_message=req.message,
        system_prompt=req.system_prompt,
        stream=False,
        model_override=req.model or None,
        think_mode=req.think_mode,
    )
    return result


@app.get("/api/tools")
async def list_tools():
    return {"tools": registry.list_tools(), "count": len(registry._tools)}


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": memory.list_sessions()}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    memory.delete(session_id)
    return {"success": True, "session_id": session_id}


@app.delete("/api/sessions")
async def clear_sessions():
    count = len(memory.sessions)
    memory.clear()
    return {"success": True, "cleared": count}


# 挂载 static 目录（前端已迁移至 CDP 服务）

import httpx
from fastapi import Request

CDP_SERVICE_URL = "http://127.0.0.1:8103"


@app.get("/api/cdp/{path:path}")
async def cdp_proxy_get(path: str, request: Request):
    """代理 GET 请求到 CDP 服务，保留 query 参数"""
    qs = str(request.url.query)
    url = f"{CDP_SERVICE_URL}/api/cdp/{path}"
    if qs:
        url += f"?{qs}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        return r.json()


@app.post("/api/cdp/{path:path}")
async def cdp_proxy_post(path: str, request: Request):
    """代理 POST 请求到 CDP 服务"""
    body = await request.json()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{CDP_SERVICE_URL}/api/cdp/{path}", json=body)
        return r.json()


@app.patch("/api/cdp/{path:path}")
async def cdp_proxy_patch(path: str, request: Request):
    """代理 PATCH 请求到 CDP 服务"""
    body = await request.json() if await request.body() else {}
    qs = str(request.url.query)
    url = f"{CDP_SERVICE_URL}/api/cdp/{path}"
    if qs:
        url += f"?{qs}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.patch(url, json=body)
        return r.json()


@app.delete("/api/cdp/{path:path}")
async def cdp_proxy_delete(path: str):
    """代理 DELETE 请求到 CDP 服务"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(f"{CDP_SERVICE_URL}/api/cdp/{path}")
        return r.json()


@app.get("/api/kb/{path:path}")
async def kb_proxy_get(path: str, request: Request):
    """代理 KB 请求到 CDP 服务"""
    qs = str(request.url.query)
    url = f"{CDP_SERVICE_URL}/api/kb/{path}"
    if qs:
        url += f"?{qs}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        return r.json()


@app.post("/api/kb/{path:path}")
async def kb_proxy_post(path: str, request: Request):
    """代理 KB POST 请求到 CDP 服务"""
    body = await request.json()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{CDP_SERVICE_URL}/api/kb/{path}", json=body)
        return r.json()


# 挂载 static 目录
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass
