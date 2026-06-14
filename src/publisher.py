"""Notion 发布模块。

创建结构化周报页面并追加内容块。处理分页（每次最多 100 blocks）
和 API 速率限制。
"""

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List

import requests

from .utils import CST, week_boundaries

logger = logging.getLogger(__name__)

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_PARENT_PAGE_ID = os.environ.get("NOTION_PARENT_PAGE_ID", "")
NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

MAX_BLOCKS_PER_REQUEST = 95  # 留 buffer 低于 100
PAGE_BLOCK_LIMIT = 1000


def _post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{NOTION_BASE}{path}", json=payload, headers=HEADERS, timeout=60)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        logger.warning(f"Notion 429，等待 {retry_after}s")
        time.sleep(retry_after)
        resp = requests.post(f"{NOTION_BASE}{path}", json=payload, headers=HEADERS, timeout=60)

    if not resp.ok:
        logger.error(f"Notion API error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()


def _patch(path: str, payload: dict) -> dict:
    resp = requests.patch(f"{NOTION_BASE}{path}", json=payload, headers=HEADERS, timeout=60)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        time.sleep(retry_after)
        resp = requests.patch(f"{NOTION_BASE}{path}", json=payload, headers=HEADERS, timeout=60)
    if not resp.ok:
        logger.error(f"Notion API error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()


def publish_report(report: dict) -> str:
    """将生成的报告发布到 Notion，返回新页面的 URL。"""
    if not NOTION_TOKEN or not NOTION_PARENT_PAGE_ID:
        raise RuntimeError("NOTION_TOKEN 或 NOTION_PARENT_PAGE_ID 未设置")

    ago, now = week_boundaries(7)
    date_range = f"{ago.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}"
    page_title = f"半导体行业周报 | {date_range}"

    # Step 1: 创建页面（带初始标题）
    page_payload = {
        "parent": {"page_id": NOTION_PARENT_PAGE_ID},
        "properties": {
            "title": {"title": [{"text": {"content": page_title}}]}
        },
    }
    page = _post("/pages", page_payload)
    page_id = page["id"]
    logger.info(f"Notion 页面已创建: {page_id}")

    # Step 2: 构建所有内容块
    blocks = _build_blocks(report, date_range)

    # Step 3: 分批追加（每批 ≤ 95 块）
    total = len(blocks)
    for offset in range(0, total, MAX_BLOCKS_PER_REQUEST):
        batch = blocks[offset : offset + MAX_BLOCKS_PER_REQUEST]
        logger.info(f"追加 {len(batch)} 个块 (offset={offset}/{total})")
        _patch(f"/blocks/{page_id}/children", {"children": batch})

    page_url = f"https://www.notion.so/{page_id.replace('-', '')}"
    logger.info(f"Notion 发布完成: {page_url}")
    return page_url


def _build_blocks(report: dict, date_range: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []

    # 目录
    blocks.append(_table_of_contents())

    # 本周概览
    blocks.append(_heading_1("本周概览"))
    exec_summary = report.get("executive_summary", "暂无数据")
    blocks.append(_paragraph(exec_summary))
    blocks.append(_divider())

    # 本周趋势
    trends = report.get("trends", [])
    if trends:
        blocks.append(_heading_1("本周关键趋势"))
        for t in trends:
            blocks.append(_bulleted_item(t))
        blocks.append(_divider())

    # 按领域逐节展示
    stats = _build_stats(report)
    blocks.append(_heading_1("数据统计"))
    blocks.append(_paragraph(stats))
    blocks.append(_divider())

    for sec in report.get("sections", []):
        label = sec.get("label", "未分类")
        articles = sec.get("articles", [])
        if not articles:
            continue

        blocks.append(_heading_1(label))
        blocks.append(_paragraph(f"本节共 {len(articles)} 条"))

        for art in articles:
            _build_article_blocks(art, blocks)

    # 学术论文清单
    papers = report.get("academic_papers", [])
    if papers:
        blocks.append(_heading_1("学术论文筛选清单"))
        blocks.append(
            _paragraph(
                "以下论文已标记优先级。请手动下载 high 和 medium 标记的论文全文，"
                "然后将 PDF 路径提供给 AI 工具进行深度分析。"
            )
        )
        for p in papers:
            rec = p.get("recommendation", "medium")
            emoji = {"high": "★", "medium": "●", "low": "○"}.get(rec, "●")
            item_text = f"{emoji} [{p.get('title', '')}]({p.get('url', '')})\\n{p.get('summary_cn', '')}"
            blocks.append(_bulleted_item(item_text))

    # 页脚
    blocks.append(_divider())
    blocks.append(
        _paragraph(
            f"本报告由半导体行业新闻机器人自动生成 | {date_range} | "
            f"生成时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M CST')}"
        )
    )
    return blocks


def _build_article_blocks(art: dict, blocks: list) -> None:
    """将单篇文章转为若干 Notion blocks 追加到列表中。"""
    title = art.get("title", "无标题")
    url = art.get("url", "")
    source = art.get("source", "")
    date = art.get("date", "")
    summary = art.get("summary_cn", "")
    importance = art.get("importance", "medium")

    imp_map = {"high": "★ 重要", "medium": "●", "low": "○"}
    imp_label = imp_map.get(importance, "●")

    # 标题（可点击）
    if url:
        title_block = _heading_3("")
        rich = title_block["heading_3"]["rich_text"]
        rich.append(_link_text(title, url))
        blocks.append(title_block)
    else:
        blocks.append(_heading_3(title))

    # 元信息
    meta = imp_label
    if source:
        meta += f"  |  {source}"
    if date:
        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            meta += f"  |  {dt.strftime('%m-%d %H:%M')}"
        except Exception:
            meta += f"  |  {date}"
    blocks.append(_paragraph(meta, color="gray"))

    # 摘要
    if summary:
        blocks.append(_paragraph(summary))

    blocks.append(_divider())


def _build_stats(report: dict) -> str:
    total = 0
    high = 0
    for sec in report.get("sections", []):
        for a in sec.get("articles", []):
            total += 1
            if a.get("importance") == "high":
                high += 1
    return (
        f"本周共收录 {total} 条行业动态，其中重点事件 {high} 条。"
        f"覆盖 {len(report.get('sections', []))} 个领域。"
    )


# ── Block builders ───────────────────────────────────────────


def _heading_1(text: str) -> dict:
    return {
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _heading_2(text: str) -> dict:
    return {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _heading_3(text: str) -> dict:
    return {
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _paragraph(text: str, color: str = "default") -> dict:
    return {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": text},
                    "annotations": {"color": color},
                }
            ]
        },
    }


def _bulleted_item(text: str) -> dict:
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def _divider() -> dict:
    return {"type": "divider", "divider": {}}


def _table_of_contents() -> dict:
    return {"type": "table_of_contents", "table_of_contents": {}}


def _link_text(text: str, url: str) -> dict:
    return {
        "type": "text",
        "text": {"content": text, "link": {"url": url}},
    }
