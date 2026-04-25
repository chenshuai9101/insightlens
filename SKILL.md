---
name: insightlens
description: |
  InsightLens — Agent 原生网页提取器。

  把网页（文章/产品/表格/列表）变成 Agent 可以直接吃的结构化 JSON。
  不光能提取，还能搜索、监控变更、关联回忆。
---

# 🔍 InsightLens — 网页结构化提取器

> **另一个网页阅读工具？不，这是 Agent 的专属感知层。**

InsightLens 是一个专为 AI Agent 设计的**网页信息提取引擎**。
它不返回 HTML 或需要人工阅读的网页渲染，而是直接把网页变成**Agent 可消费的结构化 JSON**。

## 🎯 一句话

**输入：** 一个 URL → **输出：** { title, description, content_markdown, tables[], links[], metadata{}, agent_summary{} }

## ✨ 四大核心能力

| 能力 | 说明 |
|:---|:------|
| **extract(url)** | 网页结构化提取 — 智能识别页面类型，转为 Markdown + 表格/链接 |
| **search(query, platform)** | 语义搜索 — 复用 DuckDuckGo，支持指定平台限定 |
| **subscribe(url, interval)** | 变更监控 — 定时抓取，检测变化自动通知 |
| **recall(topic)** | 记忆关联 — 基于提取历史，按主题关联检索 |

## 🚀 使用方式

### 方式一：Python SDK（推荐给 Agent 开发者）

```python
from insightlens.lens_engine import LensEngine
import asyncio

engine = LensEngine()

# 1️⃣ 提取网页
result = await engine.extract(
    "https://example.com/article",
    instruction="提取产品价格和描述"
)
print(result["title"])
print(result["content_markdown"][:200])

# 2️⃣ 搜索
search_result = await engine.search(
    "量子计算 最新进展",
    platform="知乎",
    limit=10
)
for item in search_result["results"]:
    print(f"[{item['platform']}] {item['title']}")

# 3️⃣ 订阅变更监控
sub = await engine.subscribe(
    "https://example.com/price-page",
    interval_minutes=30,
    callback_url="https://my-webhook.example.com/notify"
)
print(f"订阅ID: {sub['subscription_id']}")

# 4️⃣ 按主题回忆
memory = await engine.recall("量子计算")
for item in memory["items"]:
    print(f"📌 {item['title']} — {item['summary'][:60]}...")
```

### 方式二：MCP Server（推荐给 OpenClaw Agent）

```python
# 在终端中启动 MCP Server
python3 -m mcp_server
```

注册到 OpenClaw：

```bash
openclaw mcp set insightlens "python3 /path/to/insightlens-skill/mcp_server.py"
```

之后 Agent 就可以直接调用 `extract`/`search`/`subscribe`/`recall` 工具了。

### 方式三：一键脚本

```bash
bash scripts/start.sh
```

直接启动 MCP Server 的 stdio 循环。

## 🏗️ 包结构

```
insightlens-skill/
├── SKILL.md                  ← 你在这里
├── lens_engine.py            ← 核心引擎（统一入口）
├── extractor.py              ← 网页提取器（URL → 结构化）
├── searcher.py               ← 搜索引擎（DuckDuckGo）
├── subscriber.py             ← 变更监控订阅
├── recaller.py               ← 浏览历史关联记忆
├── models.py                 ← 数据模型
├── mcp_server.py             ← MCP Server（JSON-RPC over stdio）
├── requirements.txt          ← 依赖（bs4 + lxml + httpx）
├── assets/
│   ├── wechat_pay.jpg        ← 微信打赏码
│   └── alipay.jpg            ← 支付宝打赏码
├── scripts/
│   ├── start.sh              ← 一键启动
│   └── build-skill.sh        ← 构建打包
└── tests/                    ← 单元测试
```

## 🆚 与传统方案对比

| 场景 | Readability / Mozilla Fathom | InsightLens |
|:---|:------------------------|:-----------|
| 输出格式 | 纯文本/Markdown | **结构化 JSON**（含表格/链接/图片） |
| 页面类型 | 限文章类 | **自动识别**文章/产品/列表/表格 |
| 搜索 | ❌ 不支持 | ✅ DuckDuckGo 集成，支持平台限定 |
| 变更监控 | ❌ 不支持 | ✅ 定时检测，回调通知 |
| 关联记忆 | ❌ 不支持 | ✅ 浏览历史主题关联 |
| 输出目标 | 给人阅读 | **给 Agent 消费** |

## 🛠️ 技术特点

### 1. 零特定 CSS 选择器依赖

InsightLens 不依赖任何特定的 CSS 选择器或 XPath。
它基于**语义标签**（`<article>`、`<main>`、`[role=main]`）和**视觉结构推断**来定位主内容区。

当页面改版时，提取逻辑无需修改。

### 2. 错误恢复策略

| 错误场景 | 降级策略 |
|:--------|:--------|
| 网络超时 | ✅ 返回最小响应带错误描述 |
| HTTP 403 | ✅ 切换 User-Agent 重试一次 |
| 连接错误 | ✅ 立即返回，不阻塞 |
| 解析失败 | ✅ 降级到纯文本提取 |
| 表格解析异常 | ✅ 跳过表格，不影响整体 |
| bs4/libxml 缺失 | ✅ 已内置 stdlib 兜底 |

### 3. 结构化输出（Agent 原生）

```json
{
  "title": "Python 异步编程指南",
  "description": "深入理解 Python async/await 模式",
  "content_markdown": "# Python 异步编程\n\n...",
  "tables": [
    {
      "caption": "对比表格",
      "headers": ["特性", "同步", "异步"],
      "rows": [
        {"cells": ["性能", "低", "高"]}
      ]
    }
  ],
  "links": [
    {"href": "https://...", "text": "相关文章", "type": "internal"}
  ],
  "metadata": {
    "page_type": "article",
    "word_count": 1200,
    "response_time_ms": 350,
    "extraction_method": "semantic"
  },
  "agent_summary": {
    "title": "Python 异步编程指南",
    "content_length": 5800,
    "table_count": 1,
    "link_count": 15,
    "page_type": "article"
  }
}
```

## 🔧 扩展

### 增加搜索平台

编辑 `searcher.py`，在 `PLATFORM_DOMAINS` 中添加新域名：

```python
PLATFORM_DOMAINS = {
    "weibo": ["weibo.com", "s.weibo.com"],
    "my_new_platform": ["myplatform.com"],
    ...
}
```

### 自定义提取策略

extractor.py 的 `_find_content_area()` 函数实现了多级内容区探测。
若要支持更多页面类型，只需扩展该类中的选择模式即可。

## ⚖️ 设计哲学

- **零依赖核心** — 提取引擎仅需要 bs4 + lxml，HTTP 请求支持 stdlib 兜底
- **离线可用** — 提取和分析完全本地，不调用任何外部 API
- **Agent 原生** — 输出即 JSON，Agent 拿到就能用
- **优雅降级** — 任何错误都不崩溃，返回最合理的降级结果
- **MIT 开源** — 随意商用，备注来源即可

## ☕ 支持作者

如果 InsightLens 帮了你的 Agent 一把，欢迎打赏一杯咖啡 ☕

| 微信 | 支付宝 |
|:---:|:-----:|
| ![wechat](assets/wechat_pay.jpg) | ![alipay](assets/alipay.jpg) |

## 📜 许可证

MIT License — 随意商用，备注来源即可。

© 2025 InsightLabs — [chenshuai9101/insightlens](https://github.com/chenshuai9101/insightlens)
