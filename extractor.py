"""
InsightLens — 网页结构化提取器

从 URL 提取结构化信息：
- 智能识别页面类型（文章/列表/产品/表格）
- 基于语义标签 + 视觉结构推断，不依赖特定 CSS 选择器
- 输出 Markdown + 结构化表格/链接/图片
- 错误恢复：网络超时/403/反爬等有降级策略
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

try:
    from .models import (
        ExtractionResult,
        Link,
        Table,
        TableRow,
   )
except ImportError:
    from models import (
        ExtractionResult,
        Link,
        Table,
        TableRow,
    )

logger = logging.getLogger(__name__)

# 常见反爬 User-Agent 轮换
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
]

# 页面类型检测关键词
PAGE_TYPE_PATTERNS = {
    "article": [
        r'article',
        r'post[-_]?content',
        r'entry[-_]?content',
        r'article[-_]?body',
        r'blog[-_]?post',
        r'news[-_]?article',
        r'main[-_]?content',
    ],
    "product": [
        r'product[-_]?info',
        r'product[-_]?detail',
        r'product[-_]?description',
        r'sku',
        r'price',
        r'add[-_]?to[-_]?cart',
        r'buy[-_]?now',
        r'product[-_]?image',
    ],
    "listing": [
        r'search[-_]?result',
        r'listing[-_]?item',
        r'grid[-_]?item',
        r'card[-_]?item',
        r'list[-_]?item',
        r'category[-_]?list',
        r'product[-_]?list',
        r'item[-_]?list',
    ],
    "table": [
        r'table',
        r'thead',
        r'tbody',
        r'tr',
        r'th',
        r'td',
        r'data[-_]?table',
        r'pricing[-_]?table',
    ],
}


def _parse_links(
    soup: Any,
    base_url: str,
    max_links: int = 100,
) -> List[Link]:
    """从 BeautifulSoup 对象中提取链接"""
    links: List[Link] = []
    seen_hrefs: set = set()

    for a_tag in soup.find_all("a", href=True)[:max_links]:
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # 转换为绝对 URL
        absolute_url = urljoin(base_url, href)

        # 判断链接类型
        parsed_base = urlparse(base_url)
        parsed_href = urlparse(absolute_url)
        if parsed_base.netloc == parsed_href.netloc:
            link_type = "internal"
        elif parsed_href.netloc:
            link_type = "external"
        else:
            link_type = "anchor"

        # 提取链接文本
        text = a_tag.get_text(strip=True)
        if not text:
            # 如果是图片链接，用 alt 或 title 替代
            img = a_tag.find("img")
            if img:
                text = img.get("alt", "") or img.get("title", "") or ""

        links.append(Link(
            href=absolute_url,
            text=text[:200],
            rel=a_tag.get("rel", ""),
            type=link_type,
        ))

    return links


def _parse_tables(soup: Any) -> List[Table]:
    """从 BeautifulSoup 对象中提取表格"""
    tables: List[Table] = []

    for html_table in soup.find_all("table"):
        table = Table()

        # 表格标题
        caption_el = html_table.find("caption")
        if caption_el:
            table.caption = caption_el.get_text(strip=True)

        # 表头
        thead = html_table.find("thead")
        if thead:
            for th in thead.find_all("th"):
                table.headers.append(th.get_text(strip=True))
        else:
            # 第一行作为表头（如果全是 th）
            first_row = html_table.find("tr")
            if first_row:
                cells = first_row.find_all("th")
                if cells:
                    table.headers = [c.get_text(strip=True) for c in cells]

        # 数据行
        tbody = html_table.find("tbody") or html_table
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            # 跳过全是 th 的行（已作为表头处理）
            if all(c.name == "th" for c in cells) and not table.headers:
                table.headers = [c.get_text(strip=True) for c in cells]
                continue
            row = TableRow(cells=[c.get_text(strip=True) for c in cells])
            table.rows.append(row)

        tables.append(table)

    return tables


def _detect_page_type(soup: Any) -> str:
    """通过语义类名检测页面类型"""
    score: Dict[str, int] = {"article": 0, "product": 0, "listing": 0, "table": 0}

    # 1. 检查 class / id 中的语义关键词
    for tag in soup.find_all(True):
        tag_classes = " ".join(tag.get("class", [])) + " " + tag.get("id", "")
        if not tag_classes:
            continue
        tag_classes = tag_classes.lower()

        for page_type, patterns in PAGE_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, tag_classes):
                    score[page_type] += 1

    # 2. 检查 meta 标签
    for meta in soup.find_all("meta"):
        prop = (meta.get("property", "") or meta.get("name", "") or "").lower()
        content = (meta.get("content", "") or "").lower()
        if any(k in prop for k in ["article", "blog", "news"]):
            score["article"] += 2
        if any(k in prop for k in ["product", "price", "og:price"]):
            score["product"] += 2

    # 3. 检查页面结构
    if soup.find("article"):
        score["article"] += 3
    if soup.find("main"):
        score["article"] += 1

    # 4. 表格密度
    table_count = len(soup.find_all("table"))
    if table_count >= 3:
        score["table"] += table_count

    # 5. 列表密度（ul/ol 中的 li 数量）
    list_items = len(soup.find_all("li"))
    if list_items >= 20:
        score["listing"] += 2

    # 返回得分最高的类型
    best = max(score, key=score.get)
    return best if score[best] > 0 else "unknown"


def _extract_title(soup: Any) -> str:
    """提取页面标题"""
    # 优先 og:title
    for meta in soup.find_all("meta"):
        if meta.get("property", "").lower() == "og:title":
            content = meta.get("content", "")
            if content:
                return content.strip()

    # h1
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    # title tag
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)

    return ""


def _extract_description(soup: Any) -> str:
    """提取页面描述"""
    # 优先 meta description
    for meta in soup.find_all("meta"):
        name = (meta.get("name", "") or meta.get("property", "") or "").lower()
        if name in ("description", "og:description", "twitter:description"):
            content = meta.get("content", "")
            if content:
                return content.strip()

    # h2
    h2 = soup.find("h2")
    if h2:
        return h2.get_text(strip=True)[:200]

    return ""


def _extract_content_markdown(soup: Any, page_type: str) -> str:
    """
    从页面提取主体内容并转为 Markdown。

    基于语义标签选择主内容区，然后转换 HTML → Markdown。
    """
    content_area = _find_content_area(soup, page_type)

    if not content_area:
        # 兜底：使用 body
        content_area = soup.find("body")
        if not content_area:
            return ""

    # 移除干扰元素
    for tag in content_area.find_all(["script", "style", "nav", "footer", "header",
                                       "aside", "noscript", "iframe", "form"]):
        tag.decompose()

    return _html_to_markdown(content_area)


def _find_content_area(soup: Any, page_type: str) -> Any:
    """
    智能查找主内容区域。

    基于语义标签选择策略，不依赖特定 CSS 选择器。
    """
    # 1. 语义标签优先
    for tag_name in ["article", "main"]:
        tag = soup.find(tag_name)
        if tag:
            return tag

    # 2. role 属性
    for role in ["main", "article", "document"]:
        tag = soup.find(attrs={"role": role})
        if tag:
            return tag

    # 3. 常见类名模式
    content_selectors = [
        ["class*=", name] for name in [
            "content", "article", "post", "entry", "main",
            "body", "article-body", "post-content",
        ]
    ]

    for class_name in ["content", "article", "post", "entry", "main", "article-body",
                        "post-content", "entry-content", "main-content", "body-content"]:
        tag = soup.find(class_=re.compile(class_name, re.I))
        if tag:
            return tag

    for id_name in ["content", "article", "main", "post", "entry",
                     "main-content", "article-body", "post-content"]:
        tag = soup.find(id=re.compile(id_name, re.I))
        if tag:
            return tag

    return None


def _html_to_markdown(element: Any) -> str:
    """
    将 HTML 元素转为 Markdown 文本。

    简单的 HTML→Markdown 转换，不引入外部库。
    """
    lines: List[str] = []

    for child in element.children:
        if not hasattr(child, "name"):
            # 纯文本节点
            text = str(child).strip()
            if text:
                lines.append(text)
            continue

        tag = child.name.lower() if child.name else ""

        try:
            if tag in ("script", "style", "noscript", "iframe", "nav", "aside"):
                continue

            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"\n{'#' * level} {text}\n")

            elif tag == "p":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"\n{text}\n")

            elif tag in ("ul", "ol"):
                for i, li in enumerate(child.find_all("li", recursive=False)):
                    prefix = "- " if tag == "ul" else f"{i + 1}. "
                    text = li.get_text(strip=True)
                    if text:
                        lines.append(f"{prefix}{text}")

            elif tag == "blockquote":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"> {text}\n")

            elif tag == "pre":
                code = child.get_text()
                lines.append(f"\n```\n{code}\n```\n")

            elif tag == "code":
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"`{text}`")

            elif tag in ("strong", "b"):
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"**{text}**")

            elif tag in ("em", "i"):
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"*{text}*")

            elif tag == "a":
                href = child.get("href", "")
                text = child.get_text(strip=True)
                if text and href:
                    lines.append(f"[{text}]({href})")
                elif text:
                    lines.append(text)

            elif tag == "img":
                src = child.get("src", "")
                alt = child.get("alt", "")
                if src:
                    lines.append(f"![{alt}]({src})")

            elif tag == "br":
                lines.append("  \n")

            elif tag in ("hr", "hr/"):
                lines.append("\n---\n")

            elif tag == "div":
                # 递归处理 div
                inner = _html_to_markdown(child).strip()
                if inner:
                    lines.append(inner)

            elif tag == "table":
                lines.append(_table_to_markdown(child))

            elif tag in ("span", "section", "header"):
                text = child.get_text(strip=True)
                if text:
                    lines.append(text)

        except Exception:
            # 单个标签解析失败不影响整体
            continue

    # 合并连续的空行
    text = "\n".join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _table_to_markdown(table_tag: Any) -> str:
    """将 HTML 表格转为 Markdown 表格"""
    md_lines: list = []
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    # 表头
    headers = rows[0].find_all(["th", "td"])
    if headers:
        header_texts = [h.get_text(strip=True) for h in headers]
        md_lines.append("| " + " | ".join(header_texts) + " |")
        md_lines.append("|" + "|".join([" --- "] * len(header_texts)) + "|")

    # 数据行
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        cell_texts = []
        for cell in cells:
            text = cell.get_text(strip=True)
            # 处理表格内的链接
            link = cell.find("a")
            if link and not text:
                text = f"[{link.get_text(strip=True)}]({link.get('href', '')})"
            cell_texts.append(text)
        if cell_texts:
            md_lines.append("| " + " | ".join(cell_texts) + " |")

    return "\n".join(md_lines)


def _extract_images(soup: Any, base_url: str, max_images: int = 50) -> List[dict]:
    """提取页面中的图片"""
    images: List[dict] = []
    seen_src: set = set()

    for img in soup.find_all("img", src=True)[:max_images]:
        src = img["src"].strip()
        if not src or src.startswith("data:"):
            continue
        if src in seen_src:
            continue
        seen_src.add(src)

        absolute_src = urljoin(base_url, src)
        images.append({
            "src": absolute_src,
            "alt": img.get("alt", ""),
            "title": img.get("title", ""),
            "width": img.get("width", ""),
            "height": img.get("height", ""),
        })

    return images


async def extract_url(
    url: str,
    instruction: Optional[str] = None,
    timeout: int = 30,
) -> ExtractionResult:
    """
    核心提取函数：URL → 结构化 JSON

    Args:
        url: 目标 URL
        instruction: 可选提取指令（暂用于上下文，未来可指导精细提取）
        timeout: 超时秒数

    Returns:
        ExtractionResult 包含结构化提取结果

    错误恢复策略：
    - 网络超时/连接错误 → 返回空的 ExtractionResult + 错误信息
    - HTTP 403 → 切换 User-Agent 重试一次
    - 解析失败 → 返回基本元数据
    """
    result = ExtractionResult()
    result.metadata.url = url
    result.metadata.fetched_at = _now_iso()
    result.metadata.extraction_method = "semantic"

    start_time = time.time()

    # ----- Step 1: 获取 HTML -----
    html_content = await _fetch_html(url, timeout)
    if html_content is None:
        result.metadata.error = "Failed to fetch URL (network error or timeout)"
        result.metadata.response_time_ms = int((time.time() - start_time) * 1000)
        return result

    # ----- Step 2: 解析 HTML -----
    soup = _parse_html(html_content)
    if soup is None:
        result.metadata.error = "Failed to parse HTML"
        result.metadata.response_time_ms = int((time.time() - start_time) * 1000)
        return result

    # ----- Step 3: 检测页面类型 -----
    page_type = _detect_page_type(soup)
    result.metadata.page_type = page_type

    # ----- Step 4: 提取元数据 -----
    result.title = _extract_title(soup)
    result.description = _extract_description(soup)

    # ----- Step 5: 提取主体内容 -----
    try:
        result.content_markdown = _extract_content_markdown(soup, page_type)
        result.metadata.word_count = len(result.content_markdown.split())
    except Exception as e:
        logger.warning(f"Content extraction failed: {e}")
        result.metadata.extraction_method = "fallback"
        # 兜底：直接取 body 文本
        body = soup.find("body")
        if body:
            for tag in body.find_all(["script", "style", "nav", "footer"]):
                tag.decompose()
            result.content_markdown = body.get_text(strip=True)[:10000]

    # ----- Step 6: 提取表格和链接 -----
    try:
        result.tables = _parse_tables(soup)
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")

    try:
        result.links = _parse_links(soup, url)
    except Exception as e:
        logger.warning(f"Link extraction failed: {e}")

    # ----- Step 7: 提取图片 -----
    try:
        result.images = _extract_images(soup, url)
    except Exception as e:
        logger.warning(f"Image extraction failed: {e}")

    # ----- 完成 -----
    elapsed = int((time.time() - start_time) * 1000)
    result.metadata.response_time_ms = elapsed

    return result


async def _fetch_html(url: str, timeout: int = 30) -> Optional[str]:
    """
    获取 URL 的 HTML 内容。

    支持重试和 User-Agent 轮换。
    """
    try:
        import httpx
    except ImportError:
        # 零依赖兜底：使用 urllib
        return _fetch_html_stdlib(url, timeout)

    # 配置 httpx
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "DNT": "1",
    }

    # 尝试 2 次
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=False,  # 忽略 SSL 证书错误
            ) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code in (403, 429) and attempt == 0:
                    # 反爬：换 UA 重试
                    headers["User-Agent"] = random.choice(USER_AGENTS)
                    await _sleep(1.0)
                    continue
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url}")
                    return None
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching {url} (attempt {attempt + 1})")
            if attempt == 0:
                await _sleep(2.0)
                continue
            return None
        except Exception as e:
            logger.warning(f"HTTP error fetching {url}: {e}")
            if attempt == 0:
                await _sleep(1.0)
                continue
            return None

    return None


def _fetch_html_stdlib(url: str, timeout: int = 30) -> Optional[str]:
    """使用 urllib 兜底获取 HTML（无 httpx 时）"""
    try:
        from urllib.request import Request, urlopen

        req = Request(
            url,
            headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"stdlib fetch failed for {url}: {e}")
    return None


def _parse_html(html_content: str) -> Any:
    """解析 HTML 文本返回 BeautifulSoup 对象"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "lxml")
        return soup
    except ImportError:
        logger.warning("BeautifulSoup not available, trying html.parser")
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            return soup
        except ImportError:
            logger.error("BeautifulSoup is required but not installed")
            return None
    except Exception as e:
        logger.warning(f"HTML parsing failed: {e}")
        return None


def _now_iso() -> str:
    """当前时间的 ISO 格式字符串"""
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


async def _sleep(seconds: float) -> None:
    """异步休眠"""
    import asyncio
    await asyncio.sleep(seconds)
