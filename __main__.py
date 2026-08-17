#!/usr/bin/env python3
"""
InsightLens — 入口点

python3 -m insightlens          启动 MCP Server（stdio）
python3 -m insightlens --http   启动 HTTP Server（端口 9091）
"""
import sys
from .mcp_server import main

if __name__ == "__main__":
    if "--http" in sys.argv:
        from . import server as http_server
        http_server.main()
    else:
        main()
