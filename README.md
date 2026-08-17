# 👁️ InsightLens — Agent-native Web Content Extractor + MCP Server

> **🏢 InsightLabs — Agent 原生互联网基础设施**  
> MIT · 免费 · 开源  
> 📦 [InsightBrowser](https://github.com/chenshuai9101/insightbrowser) · [InsightLens](https://github.com/chenshuai9101/insightlens) · [InsightSee](https://github.com/chenshuai9101/insightsee) · [InsightHub](https://github.com/chenshuai9101/insighthub)  
> ☕ 如果对你有帮助，欢迎捐赠 → assets/ 有收款码

---

Read the web. Your way. Zero dependencies.

InsightLens extracts structured content from any URL — no HTML/CSS parsing complexity, no Playwright, no Selenium. Just clean JSON your agent can use.

## Features

- **6 MCP tools**: extract, search, subscribe, recall, list_subscriptions, unsubscribe
- **Small dependency footprint**: 标准库 + `beautifulsoup4` / `lxml` / `httpx`（HTTP 模式另需 `fastapi` / `uvicorn`）
- **Smart page type detection**: article, listing, profile, search, error
- **Memory system**: cross-page topic association and recall
- **Change monitoring**: subscribe to URL changes with auto-notification
- **OpenClaw ready**: `openclaw mcp set insightlens "python3 mcp_server.py"`

## Quick Start

```bash
# MCP server
openclaw mcp set insightlens '{"command":"python3","args":["/path/to/mcp_server.py"]}'

# Or standalone
python3 -c "
import asyncio
from lens_engine import LensEngine
e = LensEngine()
r = asyncio.run(e.extract('https://example.com'))
print(r)
"

# 或启动 HTTP 服务（供 InsightHub 等外部系统调用，端口 9091）
python3 -m insightlens --http
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `extract(url, instruction)` | Extract structured content from a URL |
| `search(query, platform, limit)` | Semantic search with platform filter |
| `subscribe(url, interval_minutes, callback_url)` | Monitor web page changes |
| `recall(topic, limit)` | Cross-page memory recall |
| `list_subscriptions()` | List active subscriptions |
| `unsubscribe(subscription_id)` | Remove a subscription |

## Tests

```bash
python3 -m pytest tests/ -v  # 25/25 passing
```

## License

MIT
