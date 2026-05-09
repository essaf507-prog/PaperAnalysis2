# 📄 Paper Style Extractor
> 爬取名校公开学术论文 → 提取写作风格 → 生成可复用模板 → 润色你的论文

运行环境：Python 3.10+，IDEA 调试，Claude Code 辅助开发。

---

## 🗂 项目结构

```
paper_style_extractor/
│
├── main.py                    # 主入口：双子命令 extract / polish
├── config.py                  # 全局配置（API Key、延迟、路径等）
├── requirements.txt           # 依赖清单
├── .env.example               # 环境变量模板
│
├── modules/
│   ├── __init__.py
│   ├── scraper.py             # 【模块1】网页爬虫 + 反爬策略
│   ├── extractor.py           # 【模块2】正文提取 + 论文结构识别
│   ├── chunker.py             # 【模块3】语义分块（Chunking）
│   ├── analyzer.py            # 【模块4】Claude 语义分析
│   ├── template_generator.py  # 【模块5】风格模板聚合 + 生成
│   └── polisher.py            # 【模块6】论文润色（验收复用出口）
│
├── output/                    # 中间产物（自动创建）
├── templates/                 # 生成的风格模板（自动创建）
└── logs/                      # 运行日志（自动创建）
```

---

## 📦 模块职责

| 模块 | 文件 | 核心职责 |
|---|---|---|
| 爬虫 | `scraper.py` | 获取 HTML/PDF，含 UA 轮换、随机延迟、重试退避、代理、Selenium fallback |
| 提取 | `extractor.py` | 从 HTML/PDF 识别 Abstract/Introduction/Methods 等章节结构 |
| 分块 | `chunker.py` | 按段落边界切分 + 滑动窗口重叠，保留章节标签 |
| 分析 | `analyzer.py` | 调用 Claude API，分析句式/词汇/逻辑连接/段落风格 |
| 模板 | `template_generator.py` | 聚合所有 chunk 特征，生成 Markdown + JSON 风格模板 |
| 润色 | `polisher.py` | 读取模板，调用 Claude 对用户文本按目标风格改写，输出对比报告 |

---

## ⚙️ 配置说明（`config.py`）

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API Key（必填） | 读取环境变量 |
| `CLAUDE_MODEL` | 使用模型 | `claude-sonnet-4-20250514` |
| `CHUNK_SIZE` | 每块最大 token 估算 | `512` |
| `CHUNK_OVERLAP` | 滑动重叠 token | `64` |
| `REQUEST_DELAY_MIN/MAX` | 请求间隔（秒） | `1.5 ~ 4.5` |
| `MAX_RETRIES` | 最大重试次数 | `3` |
| `USE_PROXY` | 启用代理 | `False` |
| `USE_SELENIUM` | JS 渲染页面 fallback | `False` |

---

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
export ANTHROPIC_API_KEY="sk-ant-..."
# 或复制 .env.example 为 .env 填写

# 3. 第一步：提取论文风格模板
python main.py extract --url "https://arxiv.org/abs/2310.06825"

# 4. 第二步：润色自己的论文段落（验收复用出口）
python main.py polish --text "In this paper, we try to solve..."
python main.py polish --file my_draft.txt
```

### extract 参数说明

```bash
python main.py extract --url URL [选项]

  --url URL              目标论文 URL（必填）
  --output DIR           中间产物目录（默认 output/<id>/）
  --max-chunks N         最多分析 N 个 chunk（0=全部；测试时建议 3~5）
  --sections TYPE ...    只分析指定章节类型
                         可选: introduction methodology conclusion
                               experiments results discussion abstract
  --pdf                  强制 PDF 模式
  --api-key KEY          覆盖环境变量中的 API Key
```

### polish 参数说明

```bash
python main.py polish (--text TEXT | --file FILE) [选项]

  --text TEXT            直接传入待润色文本
  --file FILE            从 .txt 文件读取待润色文本
  --template JSON_PATH   指定模板 JSON（默认自动选最新）
  --output MD_PATH       润色报告保存路径
  --api-key KEY          覆盖环境变量中的 API Key
```

---

## 📋 验收交付物清单

运行 `extract` 后，`output/<paper_id>/` 下生成：

- [ ] `raw.html` — 原始爬取页面
- [ ] `extracted.json` — 论文结构（title + abstract + sections）
- [ ] `chunks.json` — 分块结果（含 section 标签和 token 估算）
- [ ] `analysis.json` — Claude 语义分析（句式 / 词汇 / 逻辑 / 段落）
- [ ] `templates/style_template_*.md` — 人类可读风格指南
- [ ] `templates/style_template_*.json` — 机器读取模板数据

运行 `polish` 后生成：

- [ ] `output/polish_report_<timestamp>.md` — **原文 vs 润色后对比报告（最终交付物）**
- [ ] 控制台直接打印润色结果，可立即复制使用

---

## 🌐 支持的论文来源

| 来源 | 格式 | 说明 |
|---|---|---|
| arXiv.org | HTML + PDF | 优先 HTML，自动解析 abs/pdf/html URL |
| ACL Anthology | HTML | NLP 领域论文 |
| Semantic Scholar | HTML | 通用学术搜索 |
| PubMed | HTML | 生物医学 |
| 任意公开页面 | HTML | 通用降级解析 |

---

## ⚠️ 使用须知

- 仅用于**学术研究**目的，请遵守目标网站 `robots.txt` 与使用条款
- 默认启用请求限速（1.5~4.5s 随机间隔），请勿修改为高频率
- Claude API 调用产生费用，批量处理前建议先用 `--max-chunks 3` 测试
