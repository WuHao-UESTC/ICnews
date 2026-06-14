# CLAUDE.md

## 项目概述

构建一个集成电路（半导体）行业每日新闻与报告聚合工具，自动抓取全球重要半导体公司、学术期刊、主流媒体的行业最新进展，生成详尽报告并推送至 Notion。

## 讨论原则

### 批判性思维要求
- **挑战每一个假设**：对用户提出的方案，主动指出其中的逻辑漏洞、边界条件缺失和技术可行性问题
- **追问"为什么"**：当用户提出某个技术选型或设计决策时，追问其背后的动机——是出于成本考虑、技术熟悉度、还是实际约束？
- **提出替代方案**：每次给出建议时，至少提供一个有意义的替代方案并比较优劣
- **量化成本**：所有方案必须包含对成本（金钱、时间、维护负担）的估算，不允许模糊表述

### 反馈风格
- 直接指出问题，不绕弯子。如果某个想法不可行，明确说"这不可行，因为……"
- 但永远在指出问题后给出建设性的改进方向
- 优先关注影响最大的问题，而非细枝末节
- 涉及 .env、API key、token 等敏感文件时，永远不要提交到 git

### 决策框架
1. 先明确约束条件（时间、预算、技术栈限制）
2. 再评估可行性（技术可行性、数据可获取性）
3. 然后比较方案（至少 2 个方案，含 trade-off 分析）
4. 最后给出推荐并说明理由

## 项目架构

```
news/
├── .github/
│   ├── cache/
│   │   ├── source_config.json    # 新闻源配置（38个源，可独立启禁用）
│   │   └── processed_urls.json   # 已处理 URL 去重记录（自动更新）
│   └── workflows/
│       └── weekly_report.yml     # GitHub Actions 每周调度
├── src/
│   ├── main.py                   # 入口 + 命令行参数解析
│   ├── fetcher.py                # RSS + API 抓取（ThreadPoolExecutor 并行）
│   ├── processor.py              # DeepSeek LLM 去重/分类/摘要/报告生成
│   ├── publisher.py              # Notion API 发布（分块追加以绕过100块限制）
│   └── utils.py                  # 配置加载、日期处理、去重存储
├── requirements.txt
├── .env.example
└── .gitignore
```

### 数据流

```
source_config.json → Fetcher (并行 RSS/API) → Article[]
  → 去重 (URL + 标题) → DeepSeek API (分类/摘要/趋势分析)
  → Notion API (创建页面 + 分批追加 blocks)
  → 更新 processed_urls.json
```

### 关键约束
- Notion API: 每次 append 最多 100 blocks，页面最多 1000 blocks
- 单次 DeepSeek 调用输入约 40k tokens，输出约 16k tokens，成本 ~$0.01/次
- GitHub Actions: 每周运行一次，月消耗 ~120 分钟（免费额度 2000 分钟）
- RSS 源以 `!` 结尾的 URL 标记为未验证，需要手动确认后才能启用

### 本地测试

```bash
# 安装依赖
pip install -r requirements.txt

# 测试单个源
python -m src.main --test-source tsmc

# Dry run（只抓取不调用 LLM 不发布）
python -m src.main --dry-run --verbose

# 完整运行
python -m src.main
```

### 添加新源

编辑 `.github/cache/source_config.json`，新增条目：
```json
{
  "id": "unique_id",
  "name": "显示名称",
  "url": "RSS_URL",
  "category": "分类见 categories 表",
  "language": "en|zh",
  "type": "rss|api",
  "enabled": true
}
```

### 环境变量 (Secrets)

在 GitHub 仓库 Settings → Secrets and variables → Actions 中配置：
- `NOTION_TOKEN`
- `NOTION_PARENT_PAGE_ID`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`（默认 https://api.deepseek.com/v1）
