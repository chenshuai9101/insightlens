"""
InsightLens 数据模型

结构化网页提取的结果模型。
遵循 InsightSee 哲学：零依赖、离线使用、JSON 友好输出。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================
#  网页提取输出
# ============================================================


@dataclass
class Link:
    """网页中的链接"""
    href: str
    text: str
    rel: str = ""  # rel 属性（nofollow, external 等）
    type: str = ""  # internal / external / anchor

    def to_dict(self) -> dict:
        return {"href": self.href, "text": self.text, "rel": self.rel, "type": self.type}


@dataclass
class TableRow:
    """表格行"""
    cells: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"cells": self.cells}


@dataclass
class Table:
    """网页中的表格"""
    caption: str = ""
    headers: List[str] = field(default_factory=list)
    rows: List[TableRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "caption": self.caption,
            "headers": self.headers,
            "rows": [r.to_dict() for r in self.rows],
        }


@dataclass
class ExtractionMetadata:
    """提取元数据"""
    url: str = ""
    fetched_at: str = ""
    response_time_ms: int = 0
    content_type: str = ""
    page_type: str = ""  # article / listing / product / table / unknown
    word_count: int = 0
    extraction_method: str = ""  # semantic / fallback
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionResult:
    """网页提取结果 — 结构化 JSON"""
    title: str = ""
    description: str = ""
    content_markdown: str = ""
    tables: List[Table] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    images: List[dict] = field(default_factory=list)
    metadata: ExtractionMetadata = field(default_factory=ExtractionMetadata)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "content_markdown": self.content_markdown,
            "tables": [t.to_dict() for t in self.tables],
            "links": [l.to_dict() for l in self.links],
            "images": self.images,
            "metadata": self.metadata.to_dict(),
        }

    def agent_summary(self) -> dict:
        """给 Agent 快速阅读的摘要"""
        return {
            "title": self.title[:120] if self.title else "",
            "description": self.description[:200] if self.description else "",
            "content_length": len(self.content_markdown),
            "table_count": len(self.tables),
            "link_count": len(self.links),
            "page_type": self.metadata.page_type,
            "extraction_method": self.metadata.extraction_method,
        }


# ============================================================
#  搜索结果
# ============================================================


@dataclass
class SearchResult:
    """搜索结果项"""
    title: str = ""
    url: str = ""
    snippet: str = ""
    platform: str = ""
    source: str = "duckduckgo"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "platform": self.platform,
            "source": self.source,
        }


@dataclass
class SearchResponse:
    """搜索响应"""
    query: str = ""
    platform: str = ""
    total: int = 0
    results: List[SearchResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "platform": self.platform,
            "total": self.total,
            "results": [r.to_dict() for r in self.results],
        }


# ============================================================
#  订阅模型
# ============================================================


@dataclass
class Subscription:
    """页面变更订阅"""
    id: str = ""
    url: str = ""
    interval_minutes: int = 60
    last_fetched_at: str = ""
    last_content_hash: str = ""
    created_at: str = ""
    callback_url: str = ""
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SubscriptionEvent:
    """变更事件"""
    subscription_id: str = ""
    url: str = ""
    changed_at: str = ""
    change_summary: str = ""
    previous_hash: str = ""
    current_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
#  回忆/记忆关联
# ============================================================


@dataclass
class MemoryItem:
    """已提取的页面记忆"""
    url: str = ""
    title: str = ""
    extracted_at: str = ""
    keywords: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "extracted_at": self.extracted_at,
            "keywords": self.keywords,
            "summary": self.summary[:300] if self.summary else "",
        }


@dataclass
class RecallResult:
    """回忆查询结果"""
    topic: str = ""
    total: int = 0
    items: List[MemoryItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "total": self.total,
            "items": [i.to_dict() for i in self.items],
        }
