"""文章抓取模块 — RSS feeds + API endpoints。

每个源独立抓取，单个源失败不影响全局。
"""

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import os
import re

import feedparser
import requests

from .utils import (
    clean_html,
    load_source_config,
    parse_feed_date,
    week_boundaries,
)

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 30
USER_AGENT = "SemiconductorNewsBot/1.0"
REQUEST_DELAY = 1.5


@dataclass
class Article:
    source_id: str
    source_name: str
    title: str
    url: str
    published: Optional[datetime] = None
    summary: str = ""
    content: str = ""
    category: str = "uncategorized"
    language: str = "en"
    content_hash: str = ""

    def __post_init__(self):
        self.content_hash = hashlib.md5(
            (self.url or self.title).encode()
        ).hexdigest()


_TEMPLATE_RE = re.compile(r"\{(\w+)\}")


def _resolve_url(url: str) -> str:
    """替换 URL 中的 {ENV_VAR} 占位符为环境变量值。"""
    def _replacer(m: re.Match) -> str:
        return os.environ.get(m.group(1), m.group(0))
    return _TEMPLATE_RE.sub(_replacer, url)


def fetch_rss(source: dict, since: datetime) -> List[Article]:
    """抓取单个 RSS 源，返回 since 之后的 Article 列表。"""
    url = _resolve_url(source["url"])
    if not url:
        logger.warning(f"[{source['id']}] 未配置 URL，跳过")
        return []

    logger.info(f"[{source['id']}] 开始抓取 {url}")
    try:
        feed = feedparser.parse(
            url,
            agent=USER_AGENT,
            request_headers={"Accept": "application/rss+xml, application/xml, text/xml"},
        )
    except Exception as exc:
        logger.error(f"[{source['id']}] feedparser 解析失败: {exc}")
        return []

    if feed.bozo and not feed.entries:
        logger.warning(
            f"[{source['id']}] 解析异常 (bozo={feed.bozo}), "
            f"但将继续处理 {len(feed.entries)} 条"
        )

    articles: List[Article] = []
    for entry in feed.entries:
        pub_date = parse_feed_date(entry)
        if pub_date is None:
            # 无日期默认当作近期
            pub_date = datetime.now(timezone.utc) - timedelta(hours=1)
        if pub_date < since:
            continue

        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "")
        if not title:
            continue

        summary = clean_html(getattr(entry, "summary", ""))
        content_raw = ""
        for key in ("content", "description"):
            val = getattr(entry, key, None)
            if val:
                if isinstance(val, list) and len(val) > 0:
                    content_raw = val[0].get("value", "")
                elif isinstance(val, str):
                    content_raw = val
                if content_raw:
                    break
        content = clean_html(content_raw) if content_raw else summary

        articles.append(
            Article(
                source_id=source["id"],
                source_name=source["name"],
                title=title,
                url=link,
                published=pub_date,
                summary=summary,
                content=content,
                category=source.get("category", "uncategorized"),
                language=source.get("language", "en"),
            )
        )

    logger.info(f"[{source['id']}] 抓到 {len(articles)} 篇新文章")
    return articles


def fetch_api(source: dict, since: datetime) -> List[Article]:
    """抓取 API 类型源 (arXiv 等)。"""
    url = _resolve_url(source["url"])
    if not url:
        return []

    logger.info(f"[{source['id']}] API 请求 {url[:120]}...")
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.text
    except Exception as exc:
        logger.error(f"[{source['id']}] API 请求失败: {exc}")
        return []

    # arXiv Atom feed — 复用 RSS 解析器
    if "arxiv" in source.get("id", ""):
        try:
            feed = feedparser.parse(data)
            articles: List[Article] = []
            for entry in feed.entries:
                pub_date = parse_feed_date(entry)
                if pub_date and pub_date < since:
                    continue
                title = entry.title.strip()
                link = entry.id or entry.link
                summary = clean_html(entry.summary or "")
                articles.append(
                    Article(
                        source_id=source["id"],
                        source_name=source["name"],
                        title=title,
                        url=link,
                        published=pub_date,
                        summary=summary,
                        content=summary,
                        category=source.get("category", "academic"),
                        language=source.get("language", "en"),
                    )
                )
            logger.info(f"[{source['id']}] 抓到 {len(articles)} 篇论文")
            return articles
        except Exception as exc:
            logger.error(f"[{source['id']}] arXiv 解析失败: {exc}")
            return []

    return []


def fetch_all_sources(sources: list | None = None, lookback_days: int = 7) -> List[Article]:
    """并行抓取所有源，返回合并后的 Article 列表。"""
    if sources is None:
        cfg = load_source_config()
        sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]

    since, _ = week_boundaries(lookback_days)

    all_articles: List[Article] = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {}
        for src in sources:
            fetcher = fetch_api if src.get("type") == "api" else fetch_rss
            futures[executor.submit(fetcher, src, since)] = src["id"]

        for future in as_completed(futures):
            src_id = futures[future]
            try:
                articles = future.result()
                all_articles.extend(articles)
            except Exception as exc:
                logger.error(f"[{src_id}] 抓取异常: {exc}")

    logger.info(f"总共抓到 {len(all_articles)} 篇文章 (来自 {len(sources)} 个源)")
    return all_articles


def manual_fetch_test(source_id: str) -> List[Article]:
    """供手动测试单个源：返回所有文章（不限时间）。"""
    cfg = load_source_config()
    src = next((s for s in cfg["sources"] if s["id"] == source_id), None)
    if not src:
        raise ValueError(f"未找到源: {source_id}")

    since = datetime.now(timezone.utc) - timedelta(days=365)
    fetcher = fetch_api if src.get("type") == "api" else fetch_rss
    return fetcher(src, since)
