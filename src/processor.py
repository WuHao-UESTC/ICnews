"""DeepSeek 驱动的文章处理模块。

流程：
1. 去重 — 将不同源报道同一事件的条目合并
2. 分类 — 按领域归类
3. 深度分析 — 每篇文章 150-400 字分析（事实 + 动因 + 趋势影响）
4. 趋势提炼 — 每条附加 50-120 字宏观趋势判断
5. 生成报告 — 结构化周报
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

你的任务：

1. **识别趋势**：分析所有文章，识别本周最重要的 3-5 个行业趋势或事件
2. **分类**：将文章按领域归类（制造与工艺 / 数字芯片设计 / 模拟与混合信号 / 射频与微波 /
   EDA工具链 / 存储 / 设备与材料 / 供应链与产业 / 行业动态与政策 / 学术论文）
3. **深度分析每篇文章**（150-400字）：不只是摘要，而是分析新闻背后的动因和趋势影响。
   每条 summary_cn 应回答：发生了什么 → 为什么会发生 → 对行业意味着什么
4. **趋势提炼**：每条文章附加一句 trend_analysis（50-120字），点明其关联的宏观产业趋势
5. **本周概览**：5-8 句综述本周最值得关注的产业动向

文章数据如下（JSON 格式）：
{articles_json}

请严格按照以下 JSON 格式返回（不要加 markdown 代码块标记）：

{{
  "executive_summary": "本周概览（5-8 句中文，综述本周产业动向）",
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
          "summary_cn": "深度分析（150-400字）：新闻事实 + 背后动因 + 行业影响",
          "trend_analysis": "一句话趋势提炼（50-120字），点明该新闻关联的宏观产业趋势",
          "importance": "high|medium|low"
        }}
      ]
    }}
  ],
  "academic_papers": [
    {{
      "title": "论文标题",
      "url": "链接",
      "summary_cn": "论文核心贡献与潜在应用分析（100-200字）",
      "trend_analysis": "该论文所属研究方向的趋势判断",
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
            max_tokens=32000,
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
                "summary": a.summary[:2000] if a.summary else "",
                "content_snippet": a.content[:3000] if a.content else "",
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

    return f"""你是一位资深半导体行业分析师，拥有 20 年行业研究经验。你的任务是深度分析抓取到的行业文章，生成一份高质量的中文行业周报。

分类体系：
{cat_desc}

━━━━━━━━━━━━━━━━━━━━━━
核心原则：深度 > 广度
━━━━━━━━━━━━━━━━━━━━━━

你的价值不在于复述新闻，而在于揭示每一条资讯背后的产业逻辑。阅读每篇文章时，请回答三个问题：
1. 这件事本身是什么？（事实层面）
2. 为什么会发生 / 为什么会现在发生？（动因层面）
3. 它预示着什么趋势？对产业链上下游有什么连锁影响？（趋势层面）

━━━━━━━━━━━━━━━━━━━━━━
summary_cn 写作规范
━━━━━━━━━━━━━━━━━━━━━━

每条 summary_cn 应为 150-400 字的深度分析，而非简单摘要。结构如下：
- 第一段（1-2句）：新闻核心事实，必须包含具体数据、数字、人名、公司名
- 第二段（2-4句）：背后动因分析 — 技术驱动力、市场竞争格局、政策背景、供应链逻辑
- 第三段（1-2句）：对行业的影响与趋势判断 — 这条新闻意味着什么

示例（好）：
"英特尔宣布其 18A 制程进入风险试产阶段，首批晶圆已于亚利桑那 Fab 52 下线。18A 采用 RibbonFET 环栅晶体管和 PowerVia 背面供电两大突破性技术，是英特尔 IDM 2.0 战略的关键节点。若 18A 如期在 2025 年 H2 量产，英特尔有望在晶体管密度上追平台积电 N2，从而吸引英伟达、高通等潜在代工客户回归美国本土制造。这是英特尔从 IDM 向混合代工模式转型的标志性一步，也意味着台积电在先进制程上的垄断地位可能首次面临实质性挑战。"

示例（差）：
"英特尔 18A 制程取得进展。公司表示该技术将提升芯片性能。这对英特尔很重要。"

━━━━━━━━━━━━━━━━━━━━━━
trend_analysis 写作规范
━━━━━━━━━━━━━━━━━━━━━━

trend_analysis 是 50-120 字的一句话趋势提炼，直接点明该新闻关联的宏观产业趋势。
示例："全球先进制程竞争正从单极（台积电）向多极（台积电/英特尔/三星）格局演变"

━━━━━━━━━━━━━━━━━━━━━━
其他规则
━━━━━━━━━━━━━━━━━━━━━━

- 所有输出必须是中文（专业术语可用英文标注）
- 同一事件被多个来源报道的，只保留一条（选择信息最详实、质量最高的来源）
- importance 的判断标准：
  · high: 影响行业格局的重大事件（并购、重大技术突破、政策变化、大厂战略转向、关键客户变动）
  · medium: 有意义的新产品、新技术、合作、市场变化、重要财务数据
  · low: 常规新闻、小幅更新、一般性报道
- 对于学术论文，recommendation 基于其潜在行业影响力判断（能产业化的论文标记为 high）
- 无对应文章的类别可以省略
- 本周概览 executive_summary 应为 5-8 句，综述本周最值得关注的产业动向
- 每周识别 3-5 个关键趋势（trends），每个趋势 1-2 句话
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
                "trend_analysis": "",
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
