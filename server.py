"""InsightLens HTTP Server — Agent 原生网页提取的 HTTP 接口。

让 InsightHub 等外部服务通过 REST 调用 LensEngine，
而不是只能走 stdio MCP。默认端口 9091。

启动:
    python3 server.py
    或
    python -m insightlens --http

环境变量:
    INSIGHTLENS_HTTP_PORT   监听端口（默认 9091）
    INSIGHTLENS_CORS_ORIGINS 允许的 CORS 来源，逗号分隔（默认 *）
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from lens_engine import LensEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insightlens.http")

app = FastAPI(title="InsightLens HTTP", version="1.0.0")

_cors = [o.strip() for o in os.getenv("INSIGHTLENS_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = LensEngine()


class ExtractRequest(BaseModel):
    url: str
    instruction: Optional[str] = None
    timeout: int = 30


class SearchRequest(BaseModel):
    query: str
    platform: Optional[str] = None
    limit: int = 20


class SubscribeRequest(BaseModel):
    url: str
    interval_minutes: int = 60
    callback_url: Optional[str] = None


class RecallRequest(BaseModel):
    topic: str
    limit: int = 20


@app.post("/extract")
async def extract(req: ExtractRequest):
    result = await engine.extract(req.url, instruction=req.instruction, timeout=req.timeout)
    if result.get("metadata", {}).get("error"):
        raise HTTPException(status_code=502, detail=result["metadata"]["error"])
    return result


@app.post("/search")
async def search(req: SearchRequest):
    return await engine.search(query=req.query, platform=req.platform, limit=req.limit)


@app.post("/subscribe")
async def subscribe(req: SubscribeRequest):
    return await engine.subscribe(
        req.url,
        interval_minutes=req.interval_minutes,
        callback_url=req.callback_url,
    )


@app.post("/unsubscribe")
async def unsubscribe(subscription_id: str):
    ok = await engine.unsubscribe(subscription_id)
    if not ok:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"success": True}


@app.get("/subscriptions")
async def list_subscriptions():
    return {"subscriptions": engine.list_subscriptions()}


@app.post("/recall")
async def recall(req: RecallRequest):
    return await engine.recall(topic=req.topic, limit=req.limit)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "insightlens",
        "version": "1.0.0",
    }


def main() -> None:
    import uvicorn
    port = int(os.getenv("INSIGHTLENS_HTTP_PORT", "9091"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
