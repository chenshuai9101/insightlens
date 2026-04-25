#!/usr/bin/env python3
"""
InsightLens MCP Server

通过 stdio 提供 MCP (Model Context Protocol) 接口。
使用 JSON-RPC over stdio 协议，映射四个核心工具：
  - extract(url, instruction)
  - search(query, platform, limit)
  - subscribe(url, interval_minutes, callback_url)
  - recall(topic, limit)
  - list_subscriptions()
  - unsubscribe(subscription_id)

启动方式：
  python3 mcp_server.py

注册到 OpenClaw：
  openclaw mcp set insightlens "python3 /path/to/mcp_server.py"
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import traceback
from typing import Any, Dict, Optional

try:
    from .lens_engine import LensEngine
except ImportError:
    from lens_engine import LensEngine

# 关闭 httpx 的 SSL 警告
import warnings
warnings.filterwarnings("ignore", message=".*SSL.*")

logger = logging.getLogger(__name__)

# 模块级引擎实例（单例）
_engine: Optional[LensEngine] = None


def get_engine() -> LensEngine:
    """获取或创建引擎实例"""
    global _engine
    if _engine is None:
        _engine = LensEngine()
    return _engine


# ================================================================
#  JSON-RPC over stdio 实现
# ================================================================


async def handle_request(request: dict) -> dict:
    """
    处理 JSON-RPC 请求。

    Args:
        request: JSON-RPC 请求字典
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "extract",
                    "arguments": {"url": "https://..."}
                }
            }

    Returns:
        JSON-RPC 响应字典
    """
    req_id = request.get("id", None)
    method = request.get("method", "")

    engine = get_engine()

    try:
        if method == "tools/list":
            # 返回工具列表
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": engine.list_tools(),
                },
            }

        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            result = await call_tool(engine, tool_name, arguments)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, indent=2),
                        }
                    ],
                    "is_error": False,
                },
            }

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": "pong",
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

    except Exception as e:
        logger.error(f"Request error: {e}\n{traceback.format_exc()}")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32603,
                "message": str(e),
            },
        }


async def call_tool(engine: LensEngine, tool_name: str, arguments: dict) -> Any:
    """调用具体工具"""
    if tool_name == "extract":
        url = arguments.get("url", "")
        instruction = arguments.get("instruction")
        timeout = arguments.get("timeout", 30)
        if not url:
            raise ValueError("url is required")
        return await engine.extract(url, instruction=instruction, timeout=timeout)

    elif tool_name == "search":
        query = arguments.get("query", "")
        platform = arguments.get("platform")
        limit = arguments.get("limit", 20)
        if not query:
            raise ValueError("query is required")
        return await engine.search(query, platform=platform, limit=limit)

    elif tool_name == "subscribe":
        url = arguments.get("url", "")
        interval_minutes = arguments.get("interval_minutes", 60)
        callback_url = arguments.get("callback_url")
        if not url:
            raise ValueError("url is required")
        return await engine.subscribe(url, interval_minutes=interval_minutes, callback_url=callback_url)

    elif tool_name == "recall":
        topic = arguments.get("topic", "")
        limit = arguments.get("limit", 20)
        if not topic:
            raise ValueError("topic is required")
        return await engine.recall(topic=topic, limit=limit)

    elif tool_name == "list_subscriptions":
        return {"subscriptions": engine.list_subscriptions()}

    elif tool_name == "unsubscribe":
        subscription_id = arguments.get("subscription_id", "")
        if not subscription_id:
            raise ValueError("subscription_id is required")
        return await engine.unsubscribe(subscription_id)

    else:
        raise ValueError(f"Unknown tool: {tool_name}")


# ================================================================
#  stdio 主循环
# ================================================================


async def main_loop() -> None:
    """
    stdio 主循环。

    逐行读取 stdin 的 JSON-RPC 请求，处理后写入 stdout。
    遵循 MCP 协议标准。
    """
    logger.info("InsightLens MCP Server starting...")

    # 发送初始化消息（可选，但 MCP 期望）
    startup_msg = {
        "jsonrpc": "2.0",
        "method": "log",
        "params": {
            "level": "info",
            "data": "InsightLens MCP Server ready",
        },
    }
    print(json.dumps(startup_msg), flush=True)

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                # EOF
                logger.info("stdin closed, shutting down")
                break

            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            logger.debug(f"Request: {request.get('method', 'unknown')}")

            response = await handle_request(request)
            response_json = json.dumps(response, ensure_ascii=False)

            sys.stdout.write(response_json + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError as e:
            # 无效的 JSON
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {e}",
                },
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()

        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down")
            break

        except Exception as e:
            logger.error(f"Main loop error: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {e}",
                },
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()


def main() -> None:
    """入口函数"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # 日志输出到 stderr，不干扰 stdout 的 JSON-RPC
    )
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
