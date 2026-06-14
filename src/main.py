"""半导体行业周报 — 主入口。

协调抓取 → 处理 → 发布全流程。
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 本地开发时加载 .env 文件
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from .fetcher import fetch_all_sources, manual_fetch_test
from .processor import deduplicate, filter_low_importance, generate_report
from .publisher import publish_report
from .utils import (
    CST,
    load_processed_urls,
    load_source_config,
    save_processed_urls,
    week_boundaries,
)

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 降低第三方库的日志级别
    for mod in ("urllib3", "httpx", "httpcore", "openai"):
        logging.getLogger(mod).setLevel(logging.WARNING)


def run_full_pipeline(
    dry_run: bool = False,
    min_importance: str = "low",
    skip_processed: bool = True,
) -> dict | None:
    """执行完整的周报生成流程。

    Args:
        dry_run: 如果为 True，不实际发布到 Notion
        min_importance: 最低重要度 ("high", "medium", "low")
        skip_processed: 跳过已处理的 URL

    Returns:
        报告 dict，如果无新内容返回 None
    """
    logger.info("=" * 60)
    logger.info("半导体行业周报 — 开始执行")
    logger.info(f"时间: {datetime.now(CST).isoformat()}")
    logger.info("=" * 60)

    # 1. 加载已处理 URL
    processed = load_processed_urls() if skip_processed else set()
    logger.info(f"已加载 {len(processed)} 条历史 URL")

    # 2. 抓取
    cfg = load_source_config()
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    enabled_count = len(sources)
    logger.info(f"待抓取源: {enabled_count} 个")
    articles = fetch_all_sources(sources)
    if not articles:
        logger.warning("没有抓到任何文章，退出")
        return None

    # 3. 过滤已处理的
    if skip_processed:
        new_articles = [a for a in articles if a.url not in processed]
        logger.info(f"过滤后新文章: {len(new_articles)} 篇 (去除 {len(articles) - len(new_articles)} 篇已处理)")
        articles = new_articles

    if not articles:
        logger.info("没有新文章，退出")
        return None

    # 4. 去重
    articles = deduplicate(articles)

    if not articles:
        logger.info("去重后无剩余文章，退出")
        return None

    logger.info(f"去重后: {len(articles)} 篇文章，准备交给 LLM 处理")

    # 5. LLM 处理
    if dry_run:
        logger.info("DRY RUN: 跳过 LLM 调用")
        report = _empty_report(articles)
    else:
        report = generate_report(articles)

    # 6. 可选：过滤低重要度
    if min_importance != "low":
        report = filter_low_importance(report, min_importance)

    # 7. 发布到 Notion
    if dry_run:
        logger.info("DRY RUN: 跳过 Notion 发布")
        _print_summary(report)
    else:
        url = publish_report(report)
        logger.info(f"报告已发布: {url}")

    # 8. 保存已处理 URL
    new_urls = {a.url for a in articles}
    save_processed_urls(processed | new_urls)
    logger.info(f"已更新处理记录，累计 {len(processed) + len(new_urls)} 条 URL")

    return report


def _print_summary(report: dict) -> None:
    """在控制台打印报告摘要。"""
    print("\n" + "=" * 60)
    print("报告摘要 (DRY RUN)")
    print("=" * 60)
    print(f"\n本周概览: {report.get('executive_summary', 'N/A')[:300]}\n")
    trends = report.get("trends", [])
    if trends:
        print("趋势:")
        for t in trends:
            print(f"  - {t}")
    total = sum(len(s.get("articles", [])) for s in report.get("sections", []))
    print(f"\n总计 {total} 篇文章，分布在 {len(report.get('sections', []))} 个领域")


def _empty_report(articles: list) -> dict:
    """生成空报告（dry-run 用）。"""
    from .processor import CATEGORY_LABELS

    sections = {}
    for a in articles:
        sec = sections.setdefault(a.category, [])
        sec.append(
            {
                "title": a.title,
                "url": a.url,
                "source": a.source_name,
                "date": a.published.isoformat() if a.published else "",
                "summary_cn": a.summary[:300] if a.summary else a.title,
                "importance": "medium",
            }
        )
    return {
        "executive_summary": "（Dry run — 未经 LLM 处理）",
        "trends": [],
        "sections": [
            {"label": CATEGORY_LABELS.get(k, k), "articles": v}
            for k, v in sections.items()
        ],
        "academic_papers": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="半导体行业周报生成器")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不调用 LLM 也不发布到 Notion，仅抓取并打印摘要",
    )
    parser.add_argument(
        "--min-importance",
        choices=["high", "medium", "low"],
        default="low",
        help="最低重要度过滤 (默认: low)",
    )
    parser.add_argument(
        "--skip-processed",
        action="store_true",
        default=True,
        help="跳过已处理的 URL (默认)",
    )
    parser.add_argument(
        "--no-skip-processed",
        action="store_true",
        help="不跳过已处理的 URL",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细日志",
    )
    parser.add_argument(
        "--test-source",
        type=str,
        metavar="SOURCE_ID",
        help="手动测试单个源（如 tsmc）",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.test_source:
        arts = manual_fetch_test(args.test_source)
        print(f"\n{args.test_source}: 抓到 {len(arts)} 篇（不限时间）")
        for a in arts[:20]:
            print(f"  [{a.published}] {a.title[:100]}")
        return

    run_full_pipeline(
        dry_run=args.dry_run,
        min_importance=args.min_importance,
        skip_processed=not args.no_skip_processed,
    )


if __name__ == "__main__":
    main()
