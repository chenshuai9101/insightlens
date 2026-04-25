#!/usr/bin/env python3
"""
InsightLens — 单元测试

测试四个核心功能的基本正确性：
- extract: 网页提取
- search: 搜索引擎
- subscribe: 订阅管理
- recall: 记忆关联
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# 确保 insightlens 包在路径上
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    ExtractionResult,
    ExtractionMetadata,
    SearchResponse,
    SearchResult,
    Subscription,
    SubscriptionEvent,
    MemoryItem,
    RecallResult,
    Link,
    Table,
    TableRow,
)


class TestModels(unittest.TestCase):
    """数据模型测试"""

    def test_extraction_result_to_dict(self):
        result = ExtractionResult(
            title="Test Title",
            description="Test Description",
            content_markdown="# Hello",
        )
        d = result.to_dict()
        self.assertEqual(d["title"], "Test Title")
        self.assertEqual(d["content_markdown"], "# Hello")
        self.assertIsInstance(d["metadata"], dict)
        self.assertIn("page_type", d["metadata"])

    def test_extraction_result_agent_summary(self):
        result = ExtractionResult(
            title="Test",
            content_markdown="# Hello\nWorld\n",
        )
        result.metadata.page_type = "article"
        summary = result.agent_summary()
        self.assertEqual(summary["title"], "Test")
        self.assertEqual(summary["page_type"], "article")

    def test_search_response_to_dict(self):
        resp = SearchResponse(
            query="test",
            platform="zhihu",
            results=[
                SearchResult(title="A", url="https://a.com", snippet="snippet"),
                SearchResult(title="B", url="https://b.com", snippet="snippet2"),
            ],
        )
        resp.total = 2
        d = resp.to_dict()
        self.assertEqual(d["query"], "test")
        self.assertEqual(len(d["results"]), 2)

    def test_subscription_to_dict(self):
        sub = Subscription(
            id="abc123",
            url="https://example.com",
            interval_minutes=30,
        )
        d = sub.to_dict()
        self.assertEqual(d["id"], "abc123")
        self.assertTrue(d["active"])

    def test_recall_result_to_dict(self):
        result = RecallResult(
            topic="AI",
            items=[
                MemoryItem(
                    url="https://example.com/ai",
                    title="AI Guide",
                    keywords=["AI", "ML"],
                    summary="A guide to AI",
                ),
            ],
        )
        result.total = 1
        d = result.to_dict()
        self.assertEqual(d["topic"], "AI")
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["items"][0]["keywords"], ["AI", "ML"])

    def test_table_and_link(self):
        table = Table(
            caption="Data",
            headers=["A", "B"],
            rows=[TableRow(cells=["1", "2"])],
        )
        td = table.to_dict()
        self.assertEqual(td["caption"], "Data")
        self.assertEqual(td["rows"][0]["cells"], ["1", "2"])

        link = Link(href="https://x.com", text="X", type="external")
        ld = link.to_dict()
        self.assertEqual(ld["type"], "external")


class TestRecaller(unittest.TestCase):
    """记忆关联模块测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from recaller import Recaller
        self.recaller = Recaller(store_dir=self.tmpdir)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_remember_and_recall(self):
        # 记录
        self._run(self.recaller.remember(
            url="https://example.com/python",
            title="Python Async",
            content_markdown="Python async programming with asyncio",
            keywords=["Python", "async"],
        ))
        self._run(self.recaller.remember(
            url="https://example.com/ai",
            title="AI Basics",
            content_markdown="Machine learning and deep learning",
            keywords=["AI", "ML"],
        ))

        # 回忆
        result = self._run(self.recaller.recall("Python async"))
        self.assertGreaterEqual(result.total, 1)
        titles = [item.title for item in result.items]
        self.assertIn("Python Async", titles)

        # 不相关主题
        result2 = self._run(self.recaller.recall("cooking recipes"))
        self.assertEqual(result2.total, 0)

    def test_keyword_extraction(self):
        text = "Python is a great programming language for machine learning and AI"
        keywords = self.recaller._extract_keywords(text, max_keywords=5)
        self.assertTrue(len(keywords) > 0)

    def test_stats(self):
        self._run(self.recaller.remember(
            url="https://example.com/a",
            title="Article A",
            keywords=["python", "async"],
        ))
        self._run(self.recaller.remember(
            url="https://example.com/b",
            title="Article B",
            keywords=["python", "ML"],
        ))
        stats = self.recaller.stats()
        self.assertEqual(stats["total"], 2)

    def test_clear(self):
        self._run(self.recaller.remember(
            url="https://example.com/x",
            title="Test",
        ))
        self.recaller.clear()
        self.assertEqual(self.recaller.stats()["total"], 0)

    def test_url_dedup(self):
        """同一个 URL 不会重复记录"""
        self._run(self.recaller.remember(url="https://example.com/u", title="First"))
        self._run(self.recaller.remember(url="https://example.com/u", title="Updated"))
        self.assertEqual(self.recaller.stats()["total"], 1)


class TestSubscriber(unittest.TestCase):
    """订阅模块测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from subscriber import Subscriber
        self.sub = Subscriber(store_dir=self.tmpdir)

    def test_subscribe_and_unsubscribe(self):
        async def t():
            sid = await self.sub.subscribe("https://example.com", interval_minutes=10)
            self.assertIsNotNone(sid)
            self.assertEqual(len(self.sub.list_subscriptions()), 1)

            ok = await self.sub.unsubscribe(sid)
            self.assertTrue(ok)
            self.assertEqual(len(self.sub.list_subscriptions()), 0)
        asyncio.run(t())

    def test_subscribe_url_dedup(self):
        """同一个 URL 返回相同订阅"""
        async def t():
            sid1 = await self.sub.subscribe("https://example.com")
            sid2 = await self.sub.subscribe("https://example.com")
            self.assertEqual(sid1, sid2)
        asyncio.run(t())

    def test_subscription_persistence(self):
        """订阅持久化到文件"""
        async def t():
            sid = await self.sub.subscribe("https://example.org", interval_minutes=15)
            self.assertIsNotNone(sid)

            # 重新加载
            from subscriber import Subscriber
            sub2 = Subscriber(store_dir=self.tmpdir)
            self.assertEqual(len(sub2.list_subscriptions()), 1)
            self.assertEqual(sub2.list_subscriptions()[0].url, "https://example.org")
        asyncio.run(t())


class TestSearcher(unittest.TestCase):
    """搜索引擎模块测试"""

    def test_platform_resolution(self):
        from searcher import Searcher
        s = Searcher()
        self.assertEqual(s._resolve_platform("知乎"), "zhihu")
        self.assertEqual(s._resolve_platform("xiaohongshu"), "xiaohongshu")
        self.assertEqual(s._resolve_platform("weibo"), "weibo")
        self.assertIsNone(s._resolve_platform("unknown_platform_xyz"))

    def test_query_building(self):
        from searcher import Searcher
        s = Searcher()
        q = s._build_query("test query", platform="知乎")
        self.assertIn("site:zhihu.com", q)
        self.assertIn("test query", q)

        q2 = s._build_query("plain query")
        self.assertEqual(q2, "plain query")

    def test_platform_list(self):
        from searcher import Searcher
        s = Searcher()
        platforms = s.list_platforms()
        self.assertTrue(len(platforms) > 5)
        names = [p["id"] for p in platforms]
        self.assertIn("zhihu", names)
        self.assertIn("bilibili", names)

    def test_guess_platform(self):
        from searcher import Searcher
        self.assertEqual(Searcher._guess_platform("zhihu.com/question/1"), "zhihu")
        self.assertEqual(Searcher._guess_platform("weibo.com/abc"), "weibo")
        self.assertEqual(Searcher._guess_platform("unknown.example.com"), "")


class TestLensEngine(unittest.TestCase):
    """引擎集成测试"""

    def test_list_tools(self):
        from lens_engine import LensEngine
        tools = LensEngine.list_tools()
        tool_names = [t["name"] for t in tools]
        self.assertIn("extract", tool_names)
        self.assertIn("search", tool_names)
        self.assertIn("subscribe", tool_names)
        self.assertIn("recall", tool_names)
        self.assertIn("list_subscriptions", tool_names)
        self.assertIn("unsubscribe", tool_names)

    def test_tool_schemas(self):
        from lens_engine import LensEngine
        tools = LensEngine.list_tools()
        for t in tools:
            self.assertIn("input_schema", t)
            self.assertIn("description", t)
            schema = t["input_schema"]
            self.assertIn("type", schema)
            self.assertEqual(schema["type"], "object")
            self.assertIn("properties", schema)

    def test_extract_tool_params(self):
        from lens_engine import LensEngine
        tools = {t["name"]: t for t in LensEngine.list_tools()}
        extract = tools["extract"]
        required = extract["input_schema"]["required"]
        self.assertIn("url", required)

        props = extract["input_schema"]["properties"]
        self.assertIn("url", props)
        self.assertIn("instruction", props)
        self.assertIn("timeout", props)


class TestExtractor(unittest.TestCase):
    """提取器模块测试"""

    def test_page_type_detection_patterns(self):
        """验证页面类型检测模式是否存在"""
        from extractor import PAGE_TYPE_PATTERNS
        self.assertIn("article", PAGE_TYPE_PATTERNS)
        self.assertIn("product", PAGE_TYPE_PATTERNS)
        self.assertIn("listing", PAGE_TYPE_PATTERNS)
        self.assertIn("table", PAGE_TYPE_PATTERNS)
        self.assertTrue(len(PAGE_TYPE_PATTERNS["article"]) > 3)

    def test_content_area_selectors(self):
        """验证内容区选择策略的存在"""
        # 这是对 extractor 设计的一个 API 检查
        import extractor
        self.assertTrue(hasattr(extractor, "extract_url"))
        self.assertTrue(hasattr(extractor, "_find_content_area"))
        self.assertTrue(hasattr(extractor, "_detect_page_type"))
        self.assertTrue(hasattr(extractor, "_html_to_markdown"))

    def test_user_agents_exist(self):
        from extractor import USER_AGENTS
        self.assertTrue(len(USER_AGENTS) >= 3)

    def test_link_type_detection(self):
        """验证链接类型判断逻辑"""
        import extractor
        # 这个检测逻辑是写在 _parse_links 内部的
        # 我们验证函数签名
        self.assertTrue(callable(extractor._parse_links))


if __name__ == "__main__":
    unittest.main(verbosity=2)
