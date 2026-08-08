"""
InsightLens — 浏览历史关联记忆

基于提取过的 URL 历史索引，按主题关联。
使用简单的关键词提取 + TF 关联，不依赖外部数据库。
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

try:
    from .models import MemoryItem, RecallResult
except ImportError:
    from models import MemoryItem, RecallResult

logger = logging.getLogger(__name__)

# 默认存储路径
DEFAULT_STORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".insightlens_data",
    "memory",
)


class Recaller:
    """
    浏览历史关联记忆。

    基于提取过的 URL 构建索引，按主题关联检索。

    用法:
        recaller = Recaller()
        # 记录一次提取
        await recaller.remember(url="https://...", title="...", keywords=["AI","ML"])
        # 按主题回忆
        result = await recaller.recall("机器学习")
    """

    def __init__(self, store_dir: Optional[str] = None):
        self.store_dir = store_dir or DEFAULT_STORE_DIR
        os.makedirs(self.store_dir, exist_ok=True)
        self._memory: List[dict] = []
        self._load_memory()

    # ---- 记录 ----

    async def remember(
        self,
        url: str,
        title: str = "",
        content_markdown: str = "",
        summary: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> None:
        """
        记录一次网页提取到记忆库。

        Args:
            url: 页面 URL
            title: 页面标题
            content_markdown: 提取的 Markdown 内容
            summary: 自定义摘要（可选）
            keywords: 自定义关键词（可选）
        """
        # 去重：检查是否已记录
        for item in self._memory:
            if item["url"] == url:
                logger.info(f"URL already in memory, updating: {url}")
                item["title"] = title
                item["extracted_at"] = _now_iso()
                if keywords:
                    item["keywords"] = self._merge_keywords(item.get("keywords", []), keywords)
                if summary:
                    item["summary"] = summary
                elif content_markdown:
                    item["summary"] = self._auto_summarize(content_markdown)
                self._save_memory()
                return

        # 自动生成关键词
        if not keywords and content_markdown:
            keywords = self._extract_keywords(title + " " + content_markdown[:500])

        # 自动生成摘要
        if not summary and content_markdown:
            summary = self._auto_summarize(content_markdown)

        memory_item = {
            "url": url,
            "title": title or self._url_to_title(url),
            "extracted_at": _now_iso(),
            "keywords": keywords or [],
            "summary": summary or "",
        }

        self._memory.append(memory_item)
        self._save_memory()

        logger.info(f"Remembered: {url} ({len(keywords or [])} keywords)")

    def _auto_summarize(self, text: str, max_chars: int = 200) -> str:
        """自动生成摘要：取前 N 个字符"""
        # 清理文本
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."

    def _extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        """
        从文本中自动提取关键词。

        使用简单的词频统计 + 停用词过滤。
        """
        # 简单中文分词：按非中文字符切割
        # 获取中文字词
        chinese_chars = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        chinese_freq = Counter(chinese_chars)

        # 获取英文单词
        english_words = re.findall(r'[a-zA-Z]{3,}', text.lower())
        english_freq = Counter(english_words)

        # 合并，按频率排序
        all_terms = chinese_freq + english_freq

        # 过滤停用词
        stopwords = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "has", "have", "been",
            "some", "them", "then", "this", "that", "with", "from", "they",
            "what", "when", "where", "which", "their", "there", "would",
            "about", "could", "should", "非常", "一个", "没有", "可以",
            "这个", "那个", "就是", "不是", "什么", "因为", "所以", "已经",
            "但是", "如果", "对于", "还是", "这些", "那些", "怎么", "如何",
            "我们", "他们", "你们", "自己", "知道",
        }

        keywords = [
            word for word, count in all_terms.most_common(50)
            if word not in stopwords and len(word) >= 2
        ]

        return keywords[:max_keywords]

    def _merge_keywords(self, existing: List[str], new: List[str]) -> List[str]:
        """合并关键词列表（去重）"""
        seen = set(existing)
        for kw in new:
            if kw not in seen:
                seen.add(kw)
                existing.append(kw)
        return existing[:20]

    @staticmethod
    def _url_to_title(url: str) -> str:
        """URL 转标题兜底"""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            return path.replace("/", " › ").replace("-", " ").replace("_", " ")
        return parsed.netloc

    # ---- 回忆 ----

    async def recall(self, topic: str, limit: int = 20) -> RecallResult:
        """
        按主题关联回忆。

        Args:
            topic: 主题关键词
            limit: 最大返回数

        Returns:
            RecallResult 包含相关页面的列表
        """
        result = RecallResult(topic=topic)

        if not self._memory:
            return result

        # 对 topic 做简单分词
        topic_terms = set(self._tokenize(topic))

        scored: List[tuple] = []
        for item in self._memory:
            score = 0
            text_to_match = (
                item.get("title", "") + " " +
                " ".join(item.get("keywords", [])) + " " +
                item.get("summary", "")
            ).lower()

            # 2. 关键词匹配
            for term in topic_terms:
                if term in text_to_match:
                    score += 2

            # 3. 标题优先
            if any(term in item.get("title", "").lower() for term in topic_terms):
                score += 3

            if score > 0:
                scored.append((score, item))

        # 按分数降序排列
        scored.sort(key=lambda x: -x[0])

        result.items = [
            MemoryItem(
                url=item["url"],
                title=item.get("title", ""),
                extracted_at=item.get("extracted_at", ""),
                keywords=item.get("keywords", []),
                summary=item.get("summary", "")[:300],
            )
            for _, item in scored[:limit]
        ]
        result.total = len(result.items)

        return result

    def _tokenize(self, text: str) -> List[str]:
        """简单分词（中文 + 英文）"""
        tokens = []

        # 中文双字及以上
        chinese = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        tokens.extend(chinese)

        # 英文词
        english = re.findall(r'[a-zA-Z]{3,}', text.lower())
        tokens.extend(english)

        # 也加空格分词
        for part in text.split():
            if len(part) >= 2:
                tokens.append(part.lower())

        return tokens

    # ---- 统计 ----

    def stats(self) -> dict:
        """获取记忆库统计"""
        if not self._memory:
            return {"total": 0}

        all_keywords = Counter()
        for item in self._memory:
            for kw in item.get("keywords", []):
                all_keywords[kw] += 1

        top_topics = all_keywords.most_common(20)

        return {
            "total": len(self._memory),
            "unique_urls": len(set(item["url"] for item in self._memory)),
            "top_topics": [
                {"keyword": kw, "count": count}
                for kw, count in top_topics[:10]
            ],
        }

    def clear(self) -> None:
        """清空记忆库"""
        self._memory = []
        self._save_memory()

    # ---- 持久化 ----

    def _memory_path(self) -> str:
        return os.path.join(self.store_dir, "memory.json")

    def _save_memory(self) -> None:
        """保存记忆到 JSON"""
        path = self._memory_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save memory: {e}")

    def _load_memory(self) -> None:
        """从 JSON 加载记忆"""
        path = self._memory_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._memory = data if isinstance(data, list) else []
            logger.info(f"Loaded {len(self._memory)} memory items")
        except Exception as e:
            logger.warning(f"Failed to load memory: {e}")


def _now_iso() -> str:
    """当前时间的 ISO 格式字符串"""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ===================== 测试 =====================
if __name__ == "__main__":
    import asyncio
    import tempfile

    async def test():
        with tempfile.TemporaryDirectory() as tmpdir:
            r = Recaller(store_dir=tmpdir)

            # 记录一些页面
            await r.remember(
                url="https://example.com/python-async",
                title="Python 异步编程指南",
                content_markdown="Python 的 async/await 语法让异步编程变得简单。本文介绍协程、事件循环等概念。",
                keywords=["Python", "异步", "协程"],
            )
            await r.remember(
                url="https://example.com/machine-learning",
                title="机器学习入门教程",
                content_markdown="机器学习是 AI 的核心领域，包括监督学习、无监督学习等。",
                keywords=["机器学习", "AI", "监督学习"],
            )

            # 回忆
            result = await r.recall("Python 异步")
            print(f"🔍 回忆「Python 异步」: {result.total} 条")
            for item in result.items:
                print(f"  📌 {item.title}")
                print(f"     关键词: {', '.join(item.keywords)}")
                print(f"     摘要: {item.summary[:60]}...")
                print()

            result2 = await r.recall("AI 机器学习")
            print(f"🔍 回忆「AI 机器学习」: {result2.total} 条")
            for item in result2.items:
                print(f"  📌 {item.title}")

            # 统计
            stats = r.stats()
            print(f"\n📊 记忆库统计: {stats['total']} 条")

    asyncio.run(test())
