"""DeepSeek 驱动的文章处理模块。

流程：
1. 去重 — 将不同源报道同一事件的条目合并
2. 分类 — 按领域归类
3. 摘要 — 每篇文章 2-3 句总结
4. 生成报告 — 结构化周报
"""

import json
import logging
import os
from typing import List, Optional

from openai import OpenAI

from .fetcher import Article
from .utils import load_source_config

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

CATEGORY_LABELS = {
    "manufacturing": "制造与工艺",
    "digital": "芯片设计·数字与架构",
    "analog": "芯片设计·模拟与混合信号",
    "rf": "芯片设计·射频与微波",
    "eda": "芯片设计·EDA工具链",
    "memory": "存储",
    "equipment": "设备与材料",
    "supply_chain": "供应链与产业链",
    "industry": "行业动态与政策",
    "academic": "学术论文",
}


def _get_client() -> OpenAI:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置")
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def deduplicate(articles: List[Article]) -> List[Article]:
    """URL 精确去重 + 标题相似度去重。

    返回去重后的文章列表。注意这只是粗筛——同一事件不同标题的
    情况留给 LLM 在 report generation 阶段处理。
    """
    seen_urls: set = set()
    seen_titles: set = set()
    deduped: List[Article] = []

    for a in articles:
        # URL 去重
        norm_url = a.url.strip().rstrip("/")
        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        # 标题简单去重（转小写去空格）
        norm_title = "".join(a.title.lower().split())
        if norm_title in seen_titles:
            continue
        seen_titles.add(norm_title)

        deduped.append(a)

    removed = len(articles) - len(deduped)
    if removed:
        logger.info(f"去重移除 {removed} 篇重复文章，剩余 {len(deduped)} 篇")
    return deduped


def generate_report(articles: List[Article]) -> dict:
    """调用 DeepSeek 生成结构化周报。

    返回一个 dict，包含：
    - executive_summary: str
    - highlights: list[str]
    - sections: list[dict]  (label, articles)
    - academic_papers: list[dict]
    - report_date_range: str
    """
    client = _get_client()

    articles_json = _serialize_articles(articles)

    system_prompt = _build_system_prompt()
    user_prompt = f"""以下是本周（过去 7 天）抓取的半导体行业文章，共 {len(articles)} 篇。

请你完成以下任务：
1. 分析所有文章，识别本周最重要的 3-5 个行业趋势或事件
2. 将文章按领域分类（制造与工艺 / 数字芯片设计 / 模拟与混合信号 / 射频与微波 /
   EDA工具链 / 存储 / 设备与材料 / 供应链与产业 / 行业动态与政策 / 学术论文）
3. 每篇文章写 2-3 句中文摘要（保留原文关键数据和人名）
4. 生成一份 3-4 句的"本周概览"

文章数据如下（JSON 格式）：
{articles_json}

请严格按照以下 JSON 格式返回（不要加 markdown 代码块标记）：

{{
  "executive_summary": "本周概览（3-4 句中文）",
  "trends": ["趋势1", "趋势2", "趋势3"],
  "sections": [
    {{
      "label": "分类名称",
      "articles": [
        {{
          "title": "原标题",
          "url": "原文链接",
          "source": "来源名称",
          "date": "日期",
          "summary_cn": "2-3 句中文摘要",
          "importance": "high|medium|low"
        }}
      ]
    }}
  ],
  "academic_papers": [
    {{
      "title": "论文标题",
      "url": "链接",
      "summary_cn": "简短中文摘要",
      "recommendation": "high|medium|low"
    }}
  ]
}}"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=16000,
        )
        raw = response.choices[0].message.content
        logger.info(f"DeepSeek 返回 {len(raw or '')} 字符")

        # 清理可能的 markdown 代码块
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines)

        report = json.loads(raw)
        logger.info("报告生成成功")
        return report

    except json.JSONDecodeError as exc:
        logger.error(f"DeepSeek 输出不是合法 JSON: {exc}")
        logger.error(f"原始输出: {raw[:2000]}")
        return _fallback_report(articles)

    except Exception as exc:
        logger.error(f"DeepSeek 调用失败: {exc}")
        return _fallback_report(articles)


def _serialize_articles(articles: List[Article]) -> str:
    """将文章列表序列化为送给 LLM 的 JSON 字符串。"""
    items = []
    for a in articles:
        items.append(
            {
                "title": a.title,
                "url": a.url,
                "source": a.source_name,
                "date": a.published.isoformat() if a.published else "unknown",
                "summary": a.summary[:800] if a.summary else "",
                "content_snippet": a.content[:1200] if a.content else "",
                "language": a.language,
            }
        )
    return json.dumps(items, ensure_ascii=False, indent=1)


def _build_system_prompt() -> str:
    cfg = load_source_config()
    cat_desc_lines = []
    for key, info in cfg.get("categories", {}).items():
        cat_desc_lines.append(f"  - {key}: {info['label']}")
    cat_desc = "\n".join(cat_desc_lines)

    return f"""你是一位资深半导体行业分析师。你的任务是分析抓取到的行业文章，生成一份结构化的中文周报。

分类体系：
{cat_desc}

要求：
- 所有输出必须是中文
- 摘要要保留原文中具体的数据、数字、人名、公司名
- 同一事件被多个来源报道的，只保留一条（选择质量最高的来源）
- importance 的判断标准：
  · high: 影响行业格局的重大事件（并购、重大技术突破、政策变化、大厂战略转向）
  · medium: 有意义的新产品、新技术、合作、市场变化
  · low: 常规新闻、小幅更新、一般性报道
- 对于学术论文，recommendation 基于其潜在行业影响力判断
- 无对应文章的类别可以省略
- 只返回 JSON，不要加任何额外文字"""


def _fallback_report(articles: List[Article]) -> dict:
    """LLM 调用失败时的降级报告。"""
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
        "executive_summary": "（本周报由自动降级流程生成，DeepSeek 分析未完成）",
        "trends": [],
        "sections": [
            {"label": CATEGORY_LABELS.get(k, k), "articles": v}
            for k, v in sections.items()
        ],
        "academic_papers": [],
    }


def filter_low_importance(report: dict, min_importance: str = "medium") -> dict:
    """筛掉低重要度的文章，返回精简报告。"""
    keep_levels = {"high", "medium"}
    if min_importance == "high":
        keep_levels = {"high"}

    filtered_sections = []
    for sec in report.get("sections", []):
        kept = [a for a in sec.get("articles", []) if a.get("importance", "medium") in keep_levels]
        if kept:
            sec["articles"] = kept
            filtered_sections.append(sec)

    report["sections"] = filtered_sections
    return report
