"""
InsightLens — 核心提取引擎

统一入口：extract / search / subscribe / recall
协调 extractor, searcher, subscriber, recaller 四个模块。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

try:
    from .extractor import extract_url as _extract_url
    from .searcher import Searcher
    from .subscriber import Subscriber
    from .recaller import Recaller
except ImportError:
    from extractor import extract_url as _extract_url
    from searcher import Searcher
    from subscriber import Subscriber
    from recaller import Recaller

logger = logging.getLogger(__name__)


class LensEngine:
    """
    InsightLens 核心引擎。

    统一的入口，提供四个主要工具方法。
    每个方法返回结构化 JSON（dict），直接可供 Agent 消费。

    用法:
        engine = LensEngine()
        result = await engine.extract("https://example.com", "提取产品信息")
        search_result = await engine.search("Python 教程", limit=10)
        sub_id = await engine.subscribe("https://example.com", interval_minutes=30)
        recall_result = await engine.recall("机器学习")
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        search_timeout: int = 15,
    ):
        self._searcher = Searcher(timeout=search_timeout)
        self._subscriber = Subscriber(store_dir=data_dir)
        self._recaller = Recaller(store_dir=data_dir)
        self._search_timeout = search_timeout

    # ================================================================
    #  1. extract(url, instruction) — 网页结构化提取
    # ================================================================

    async def extract(
        self,
        url: str,
        instruction: Optional[str] = None,
        timeout: int = 30,
    ) -> dict:
        """
        提取网页内容为结构化 JSON。

        Args:
            url: 目标 URL
            instruction: 可选提取指令（如"提取产品描述"、"提取表格数据"）
            timeout: 超时秒数

        Returns:
            dict: 结构化提取结果
                {
                    "title": "...",
                    "description": "...",
                    "content_markdown": "...",
                    "tables": [...],
                    "links": [...],
                    "images": [...],
                    "metadata": {...},
                    "agent_summary": {...}
                }

        错误恢复：
        - 网络错误 → 返回 minimal JSON 带错误信息
        - 解析失败 → 降级返回基本元数据
        """
        result = await _extract_url(url, instruction=instruction, timeout=timeout)

        # 记录到记忆库（异步，失败不阻塞）
        if result.title or result.content_markdown:
            try:
                await self._recaller.remember(
                    url=url,
                    title=result.title,
                    content_markdown=result.content_markdown[:1000],
                    keywords=[],
                )
            except Exception as e:
                logger.debug(f"Failed to remember {url}: {e}")

        output = result.to_dict()
        output["agent_summary"] = result.agent_summary()

        return output

    # ================================================================
    #  2. search(query, platform, limit) — 语义搜索
    # ================================================================

    async def search(
        self,
        query: str,
        platform: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """
        使用 DuckDuckGo 搜索网络内容。

        Args:
            query: 搜索关键词
            platform: 目标平台（如 "知乎"、"xiaohongshu"），不传则全网
            limit: 最大返回条数 1-50

        Returns:
            dict: 搜索结果
                {
                    "query": "...",
                    "platform": "...",
                    "total": 10,
                    "results": [
                        {"title": "...", "url": "...", "snippet": "...", "platform": "...", "source": "duckduckgo"},
                        ...
                    ]
                }
        """
        result = await self._searcher.search(
            query=query,
            platform=platform,
            limit=limit,
        )
        return result.to_dict()

    # ================================================================
    #  3. subscribe(url, interval_minutes) — 变更监控
    # ================================================================

    async def subscribe(
        self,
        url: str,
        interval_minutes: int = 60,
        callback_url: Optional[str] = None,
    ) -> dict:
        """
        订阅 URL 的变更监控。

        Args:
            url: 目标 URL
            interval_minutes: 检查间隔（分钟），最少 5 分钟
            callback_url: 变更时回调的 HTTP URL（POST JSON）

        Returns:
            dict: 订阅结果
                {
                    "subscription_id": "abc12345",
                    "url": "https://...",
                    "interval_minutes": 60,
                    "status": "active"
                }
        """
        sub_id = await self._subscriber.subscribe(
            url=url,
            interval_minutes=interval_minutes,
            callback_url=callback_url,
        )
        sub = self._subscriber.get_subscription(sub_id)
        if sub:
            return {
                "subscription_id": sub_id,
                "url": sub.url,
                "interval_minutes": sub.interval_minutes,
                "status": "active" if sub.active else "inactive",
            }
        return {"subscription_id": sub_id, "status": "created"}

    async def unsubscribe(self, subscription_id: str) -> dict:
        """取消订阅"""
        ok = await self._subscriber.unsubscribe(subscription_id)
        return {"subscription_id": subscription_id, "unsubscribed": ok}

    async def check_subscription(self, subscription_id: str) -> dict:
        """手动检查订阅变更"""
        events = await self._subscriber.check(subscription_id)
        return {
            "subscription_id": subscription_id,
            "changed": len(events) > 0,
            "events": [e.to_dict() for e in events],
        }

    def list_subscriptions(self) -> List[dict]:
        """列出所有活跃订阅"""
        return [s.to_dict() for s in self._subscriber.list_subscriptions()]

    # ================================================================
    #  4. recall(topic) — 浏览历史关联记忆
    # ================================================================

    async def recall(self, topic: str, limit: int = 20) -> dict:
        """
        按主题关联回忆已提取过的页面。

        Args:
            topic: 主题关键词
            limit: 最大返回数

        Returns:
            dict: 回忆结果
                {
                    "topic": "...",
                    "total": 3,
                    "items": [
                        {
                            "url": "...",
                            "title": "...",
                            "extracted_at": "...",
                            "keywords": ["...", "..."],
                            "summary": "..."
                        },
                        ...
                    ]
                }
        """
        result = await self._recaller.recall(topic=topic, limit=limit)
        return result.to_dict()

    def memory_stats(self) -> dict:
        """记忆库统计"""
        return self._recaller.stats()

    # ================================================================
    #  工具列表（MCP 注册用）
    # ================================================================

    @staticmethod
    def list_tools() -> List[dict]:
        """返回工具列表，用于 MCP 注册"""
        return [
            {
                "name": "extract",
                "description": "从 URL 提取结构化网页内容。支持文章、产品页、表格、列表等页面类型。自动识别页面类型，返回 Markdown + 结构化数据。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "目标网页 URL"},
                        "instruction": {"type": "string", "description": "可选提取指令，如'提取产品价格''提取表格数据'"},
                        "timeout": {"type": "number", "description": "超时秒数，默认30"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "search",
                "description": "搜索网络内容。使用 DuckDuckGo，支持按平台（知乎/小红书/淘宝等）限定搜索。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "platform": {"type": "string", "description": "目标平台名称（如'知乎''小红书''taobao'），不传则全网搜索"},
                        "limit": {"type": "number", "description": "最大返回条数，1-50，默认20"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "subscribe",
                "description": "订阅 URL 的变更监控。定时抓取页面，检测内容变化时通知。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "要监控的网页 URL"},
                        "interval_minutes": {"type": "number", "description": "检查间隔（分钟），最少5分钟，默认60"},
                        "callback_url": {"type": "string", "description": "变更时回调的 HTTP URL（可选）"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "recall",
                "description": "根据主题回忆已提取过的相关网页。基于浏览历史关键词和内容匹配。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "主题关键词"},
                        "limit": {"type": "number", "description": "最大返回条数，默认20"},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "list_subscriptions",
                "description": "列出当前所有活跃的网页变更监控订阅。",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "unsubscribe",
                "description": "取消一个网页变更监控订阅。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "subscription_id": {"type": "string", "description": "订阅 ID"},
                    },
                    "required": ["subscription_id"],
                },
            },
        ]


# ===================== 快速测试 =====================
if __name__ == "__main__":
    import asyncio

    async def test():
        engine = LensEngine()

        print("=" * 50)
        print("🔬 InsightLens 引擎测试")
        print("=" * 50)

        # 工具列表
        tools = engine.list_tools()
        print(f"\n📋 注册 {len(tools)} 个工具:")
        for t in tools:
            print(f"   🛠️  {t['name']}: {t['description'][:60]}...")

        # 搜索测试
        print("\n🔍 搜索测试...")
        sr = await engine.search("量子计算", limit=3)
        print(f"   找到 {sr['total']} 条结果")
        for r in sr.get("results", [])[:2]:
            print(f"   - {r['title'][:60]}")

        # 提取测试
        print("\n🌐 提取测试 (example.com)...")
        ex = await engine.extract("https://example.com")
        print(f"   标题: {ex.get('title', '')}")
        print(f"   类型: {ex.get('metadata', {}).get('page_type', '')}")
        print(f"   耗时: {ex.get('metadata', {}).get('response_time_ms', 0)}ms")

        print("\n✅ 引擎测试完成")

    asyncio.run(test())
