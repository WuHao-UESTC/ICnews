# 半导体行业周报生成器

自动抓取全球半导体行业资讯，通过 DeepSeek LLM 深度分析每篇文章背后的产业逻辑与趋势，生成结构化中文行业周报并推送至 Notion。

## 核心特性

- **22 个精选信息源** — 覆盖 Intel、NVIDIA、Samsung 等原厂博客，SemiEngineering、IEEE Spectrum、EE Times 等专业媒体，Google News 关键词聚合，arXiv 学术论文
- **全文提取** — 对 RSS 摘要不足的文章自动抓取原文正文（基于 trafilatura），确保 LLM 有足够素材做深度分析
- **深度分析而非简单摘要** — 每篇文章 150-400 字分析：新闻事实 → 背后动因 → 行业影响趋势，而非 2-3 句敷衍总结
- **趋势识别** — 每周自动提炼 3-5 个关键产业趋势，每条文章附带宏观趋势标签
- **10 大领域全覆盖** — 制造工艺、数字芯片设计、模拟混合信号、射频微波、EDA 工具链、存储、设备材料、供应链、行业政策、学术论文
- **中英双语覆盖** — 同时抓取中文和英文源
- **GitHub Actions 全自动运行** — 每周一 UTC 00:00 定时触发，无需服务器，零运维成本
- **URL 去重** — 自动记录已处理文章，避免重复报道
- **成本极低** — 单次运行 DeepSeek API 成本约 $0.01-0.03，GitHub Actions 免费额度内完全够用

## 与其他新闻聚合工具的区别

| | 本项目 | RSS Reader | 通用 AI 摘要 |
|---|---|---|---|
| 领域聚焦 | 半导体全产业链 | 通用 | 通用 |
| 分析深度 | 150-400 字/篇，含动因与趋势 | 无 | 1-2 句摘要 |
| 趋势识别 | 每期提炼产业趋势 | 无 | 无 |
| 原文获取 | RSS + 全文抓取双通道 | 仅 RSS 摘要 | 依赖用户输入 |
| 发布方式 | 自动推送到 Notion | 阅读器内查看 | 对话式 |

## 数据流

```
source_config.json (22 个源)
       │
       ▼
  RSS / API 并行抓取 (ThreadPoolExecutor, 6 workers)
       │
       ▼
  trafilatura 全文提取 (补全 RSS 摘要不足的文章)
       │
       ▼
  URL + 标题去重
       │
       ▼
  DeepSeek LLM 深度分析 (max_tokens=32k)
  · 去重合并 · 领域分类 · 深度分析 · 趋势识别
       │
       ▼
  Notion API 发布 (分块追加, 每批 ≤95 blocks)
       │
       ▼
  更新 processed_urls.json (Git 提交到仓库)
```

## 覆盖范围

### 信息源

| 类型 | 数量 | 示例 |
|---|---|---|
| 官方博客 RSS | 14 个 | Intel Newsroom, NVIDIA Blog, Samsung Semiconductor, SK Hynix |
| Google News 关键词 | 7 个 | 制造工艺、设备材料、模拟射频、EDA IP、供应链 |
| 学术 API | 1 个 | arXiv (cs.AR + cs.ET + cond-mat.mes-hall) |

### 覆盖领域

| 领域 | 说明 |
|---|---|
| 制造与工艺 | TSMC, Intel, Samsung 先进制程进展 |
| 芯片设计·数字与架构 | CPU/GPU/DPU/NPU 架构, RISC-V, Chiplet |
| 芯片设计·模拟与混合信号 | TI, ADI, 电源管理, 数据转换器 |
| 芯片设计·射频与微波 | 5G/6G, 毫米波, 射频前端 |
| 芯片设计·EDA 工具链 | Cadence, Synopsys, 设计方法学 |
| 存储 | DRAM, NAND, HBM, 新型存储 |
| 设备与材料 | ASML, Applied Materials, Lam Research |
| 供应链与产业链 | 产能, 地缘政治, 出口管制 |
| 行业动态与政策 | 并购, 财报, 各国芯片法案 |
| 学术论文 | 器件物理, 电路设计, 架构创新 |

## Fork 后使用教程

### 1. Fork 仓库

点击右上角 Fork 按钮，Fork 到你的 GitHub 账号下。

### 2. 获取 API 密钥

需要三个密钥：

**Notion**
1. 打开 [Notion Integrations](https://www.notion.so/my-integrations)，创建新集成
2. 复制 `Internal Integration Secret`（以 `ntn_` 开头）
3. 在 Notion 中创建一个页面作为周报的父页面
4. 在该页面的 `...` 菜单 → Connections → 添加你刚创建的集成
5. 从页面 URL 中获取 Page ID：`https://www.notion.so/My-Page-xxxxxxxxxxxx?v=...` 中 `xxxxxxxxxxxx` 部分（32 位）

**DeepSeek**
1. 注册 [DeepSeek Platform](https://platform.deepseek.com/)
2. 在 API Keys 页面创建新 Key（以 `sk-` 开头）
3. 充值 $1-2 即可使用数月

**IEEE Xplore（可选）**
1. 在 [developer.ieee.org](https://developer.ieee.org/) 注册获取免费 API Key
2. 如不想配置，该源默认禁用

### 3. 配置 GitHub Secrets

在 Fork 后的仓库中：Settings → Secrets and variables → Actions → New repository secret

| Secret 名称 | 值 | 必填 |
|---|---|---|
| `NOTION_TOKEN` | Notion Integration Token | ✅ |
| `NOTION_PARENT_PAGE_ID` | Notion 父页面 ID | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | ✅ |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | 可选 |
| `IEEE_API_KEY` | IEEE Xplore API Key | 可选 |

### 4. 启用 GitHub Actions

1. 进入 Actions 标签页
2. 点击 "I understand my workflows, go ahead and enable them"
3. 选择 "半导体行业周报" workflow → Enable workflow

### 5. 手动触发测试

Actions → 半导体行业周报 → Run workflow → 勾选 **Dry run** → Run workflow

Dry run 模式只抓取不调用 LLM 也不发布，适合验证网络和配置。

### 6. 首次正式运行

取消勾选 Dry run，点击 Run workflow。运行完成后检查 Notion 页面。

## 本地测试

```bash
# 克隆你的 Fork
git clone https://github.com/YOUR_USERNAME/news.git
cd news

# 安装依赖
pip install -r requirements.txt

# 创建 .env 文件，填入密钥
cp .env.example .env
# 编辑 .env 填入实际值

# 测试单个源
python -m src.main --test-source intel

# Dry run（抓取但不调用 LLM）
python -m src.main --dry-run --verbose

# 完整运行（抓取 + LLM + Notion 发布）
python -m src.main
```

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--dry-run` | 不调用 LLM，不发布 Notion |
| `--verbose` / `-v` | 输出详细日志 |
| `--test-source SOURCE_ID` | 手动测试单个源（不限时间范围） |
| `--min-importance low\|medium\|high` | 过滤低重要度文章 |
| `--no-skip-processed` | 重新处理已处理过的 URL |

## 添加自定义信息源

编辑 `.github/cache/source_config.json`，在 `sources` 数组中新增：

```json
{
  "id": "my_custom_source",
  "name": "我的信息源",
  "url": "https://example.com/feed/",
  "category": "digital",
  "language": "en",
  "type": "rss",
  "enabled": true,
  "note": "备注说明"
}
```

字段说明：
- `id` — 唯一标识符
- `name` — 显示名称
- `url` — RSS/API 地址。支持 `{ENV_VAR}` 模板语法引用环境变量
- `category` — 分类（见上文覆盖领域表）
- `language` — `en` 或 `zh`
- `type` — `rss` 或 `api`
- `enabled` — `true` 启用，`false` 禁用
- `note` — 备注（可选）

提交后 GitHub Actions 下次运行会自动加载新源。

## 报告内容结构

每份周报包含：

1. **本周概览** — 5-8 句综述本周产业动向
2. **本周关键趋势** — 3-5 个宏观产业趋势
3. **数据统计** — 收录文章数、重点事件数、覆盖领域数
4. **分领域详情** — 每篇文章含：
   - 可点击原文标题
   - 来源 + 日期 + 重要度标记
   - **趋势标签** — 一句话点明关联的宏观趋势
   - **深度分析** — 150-400 字：事实 + 动因 + 行业影响
5. **学术论文筛选清单** — 含优先级标记

## 成本估算

| 项目 | 单次消耗 | 月消耗 |
|---|---|---|
| DeepSeek API | ~$0.02（32K tokens 输出） | ~$0.08 |
| GitHub Actions | ~6 分钟 | ~24 分钟（免费额度 2000 分钟） |
| Notion API | 免费 | 免费 |
| **合计** | **~$0.02/次** | **~$0.08/月** |

## 常见问题

**Q: Google News RSS 在国内本地测试返回 0 条？**
A: 正常，Google 服务在墙内被阻断。GitHub Actions 的 Ubuntu runner 在国外，不受影响。

**Q: arXiv API 解析报错？**
A: 墙内连接超时，GitHub Actions 中正常运行。

**Q: Notion 页面显示不全？**
A: Notion 单页面 block 上限 1000 块。如果文章数超过约 150 篇可能截断，可通过 `--min-importance medium` 精简。

**Q: 想改成日报？**
A: 修改两处：`.github/workflows/weekly_report.yml` 的 cron 改为 `0 0 * * *`，`source_config.json` 的 `lookback_days` 改为 `1`。

**Q: 想换成其他 LLM？**
A: 项目使用 OpenAI 兼容 API，修改 `.env` 中的 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL` 即可切换到任何兼容服务（如 OpenAI、Groq、通义千问等）。

## 项目结构

```
news/
├── .github/
│   ├── cache/
│   │   ├── source_config.json      # 信息源配置
│   │   └── processed_urls.json     # 已处理 URL 去重记录
│   └── workflows/
│       └── weekly_report.yml       # GitHub Actions 调度
├── src/
│   ├── main.py                     # 主入口 + CLI
│   ├── fetcher.py                  # RSS/API 抓取 + 全文提取
│   ├── processor.py                # DeepSeek 分析
│   ├── publisher.py                # Notion 发布
│   └── utils.py                    # 工具函数
├── requirements.txt
├── .env.example
└── .gitignore
```

## License

MIT
