"""
InsightLens — 搜索引擎持久层

复用 InsightSee 的 DuckDuckGo 搜索引擎。
支持指定平台搜索，返回结构化结果。
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

try:
    from .models import SearchResult, SearchResponse
except ImportError:
    from models import SearchResult, SearchResponse

logger = logging.getLogger(__name__)


# 平台到 site: 域名的映射
PLATFORM_DOMAINS = {
    "weibo": ["weibo.com", "s.weibo.com"],
    "zhihu": ["zhihu.com"],
    "xiaohongshu": ["xiaohongshu.com"],
    "taobao": ["taobao.com"],
    "dianping": ["dianping.com"],
    "douyin": ["douyin.com"],
    "bilibili": ["bilibili.com"],
    "douban": ["douban.com"],
    "baidu_tieba": ["tieba.baidu.com"],
    "jianshu": ["jianshu.com"],
    "csdn": ["csdn.net"],
    "36kr": ["36kr.com"],
}

# 平台名称映射（中英文）
PLATFORM_ALIASES = {
    "微博": "weibo",
    "知乎": "zhihu",
    "小红书": "xiaohongshu",
    "小红书": "xiaohongshu",
    "淘宝": "taobao",
    "taobao": "taobao",
    "大众点评": "dianping",
    "dianping": "dianping",
    "抖音": "douyin",
    "douyin": "douyin",
    "b站": "bilibili",
    "B站": "bilibili",
    "bilibili": "bilibili",
    "豆瓣": "douban",
    "douban": "douban",
    "百度贴吧": "baidu_tieba",
    "baidu_tieba": "baidu_tieba",
    "简书": "jianshu",
    "jianshu": "jianshu",
    "csdn": "csdn",
    "36氪": "36kr",
    "36kr": "36kr",
}


class Searcher:
    """
    搜索引擎适配器。

    复用 InsightSee 的 DuckDuckGo 搜索，支持指定平台 site: 限定。

    用法:
        searcher = Searcher()
        result = await searcher.search("量子计算 最新进展", limit=10)
        result_zhihu = await searcher.search("AI 工具", platform="知乎", limit=5)
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._ddg_url = "https://html.duckduckgo.com/html/"

    def _resolve_platform(self, platform: str) -> Optional[str]:
        """将平台名称转为内部 ID"""
        return PLATFORM_ALIASES.get(platform) or (
            platform if platform in PLATFORM_DOMAINS else None
        )

    def _build_query(self, keyword: str, platform: Optional[str] = None) -> str:
        """构建 DuckDuckGo 查询字符串"""
        query = keyword
        if platform:
            platform_id = self._resolve_platform(platform)
            if platform_id:
                domains = PLATFORM_DOMAINS.get(platform_id, [])
                if domains:
                    site_parts = " OR ".join(f"site:{d}" for d in domains)
                    query = f"({site_parts}) {keyword}"
        return query

    async def search(
        self,
        query: str,
        platform: Optional[str] = None,
        limit: int = 20,
    ) -> SearchResponse:
        """
        执行搜索。

        Args:
            query: 搜索关键词
            platform: 目标平台（如 "知乎"、"xiaohongshu"），不传则全网
            limit: 最大返回条数 1-50

        Returns:
            SearchResponse 结构化结果
        """
        response = SearchResponse(query=query, platform=platform or "all")

        if limit < 1:
            return response
        limit = min(limit, 50)

        search_query = self._build_query(query, platform)

        try:
            import httpx
        except ImportError:
            logger.error("httpx required for search; install with: pip install httpx")
            return response

        user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ]

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.post(
                    self._ddg_url,
                    data={"q": search_query},
                    headers={
                        "User-Agent": user_agents[0],
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                )

                if resp.status_code != 200:
                    logger.warning(f"DuckDuckGo returned {resp.status_code}")
                    return response

                response.results = self._parse_ddg_results(
                    resp.text,
                    platform_id=self._resolve_platform(platform) if platform else "",
                )
                response.total = len(response.results)

        except Exception as e:
            logger.warning(f"Search failed: {e}")

        return response

    def _parse_ddg_results(self, html_text: str, platform_id: str) -> List[SearchResult]:
        """解析 DuckDuckGo HTML 搜索结果"""
        results: List[SearchResult] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_text, "lxml")

            for result_div in soup.select(".result"):
                try:
                    # 标题
                    title_el = result_div.select_one(".result__title a")
                    title = self._clean_text(title_el.get_text()) if title_el else ""

                    # URL
                    url = ""
                    if title_el and title_el.get("href"):
                        href = title_el["href"]
                        if "uddg=" in href:
                            import urllib.parse
                            parsed = urllib.parse.urlparse(href)
                            qs = urllib.parse.parse_qs(parsed.query)
                            url = qs.get("uddg", [""])[0]
                        else:
                            url = href

                    # 摘要
                    snippet_el = result_div.select_one(".result__snippet")
                    snippet = self._clean_text(snippet_el.get_text()) if snippet_el else ""

                    # 来源域名
                    cite_el = result_div.select_one(".result__url")
                    domain = cite_el.get_text(strip=True) if cite_el else ""

                    if snippet or title:
                        results.append(SearchResult(
                            title=title[:200],
                            url=url,
                            snippet=snippet[:300],
                            platform=platform_id or self._guess_platform(domain),
                            source="duckduckgo",
                        ))

                except Exception:
                    continue

        except ImportError:
            # BeautifulSoup 不可用时返回空
            logger.warning("BeautifulSoup not available for search parsing")

        return results[:50]

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理 HTML 标签和多余的空白"""
        import html
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def _guess_platform(domain: str) -> str:
        """从域名推测平台"""
        domain = domain.lower()
        for name, domains in PLATFORM_DOMAINS.items():
            for d in domains:
                if d in domain:
                    return name
        return ""

    @staticmethod
    def list_platforms() -> List[dict]:
        """列出支持的平台"""
        return [
            {
                "id": pid,
                "name": next((k for k, v in PLATFORM_ALIASES.items() if v == pid and k != pid), pid),
                "domain": domains[0],
            }
            for pid, domains in PLATFORM_DOMAINS.items()
        ]


# ===================== 测试 =====================
if __name__ == "__main__":
    import asyncio

    async def test():
        s = Searcher()
        print("=" * 50)
        print("🔍 测试: 全网搜索")
        r = await s.search("Python 异步编程 教程", limit=5)
        print(f"找到 {r.total} 条结果:")
        for item in r.results[:3]:
            print(f"  [{item.platform}] {item.title[:60]}")
            print(f"  → {item.snippet[:80]}...")
            print()

        print("=" * 50)
        print("🔍 测试: 知乎限定")
        r2 = await s.search("深度学习", platform="知乎", limit=3)
        print(f"找到 {r2.total} 条结果:")
        for item in r2.results[:3]:
            print(f"  {item.title[:60]}")
            print(f"  → {item.snippet[:80]}...")

    asyncio.run(test())
