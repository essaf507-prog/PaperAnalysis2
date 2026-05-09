# config.py — 全局配置
# 修改此文件调整全局行为，所有模块共享

import os
from pathlib import Path

# ── 路径 ─────────────────────────────────────
BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "output"
TEMPLATE_DIR= BASE_DIR / "templates"
LOG_DIR     = BASE_DIR / "logs"

# ── Claude API ────────────────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL       = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS  = 2048
CLAUDE_TEMPERATURE = 0.3

# ── 分块参数 ──────────────────────────────────
CHUNK_SIZE     = 512   # 每块最大 token 估算（1 token ≈ 4 字符）
CHUNK_OVERLAP  = 64    # 滑动窗口重叠 token
MIN_CHUNK_TOKENS = 80  # 过短 chunk 合并到下一块

# ── 爬虫 / 反爬 ───────────────────────────────
REQUEST_DELAY_MIN = 1.5    # 请求最小间隔（秒）
REQUEST_DELAY_MAX = 4.5    # 请求最大间隔（秒）
MAX_RETRIES       = 3      # 最大重试次数
RETRY_BACKOFF     = 2.0    # 指数退避基数
REQUEST_TIMEOUT   = 20     # 单次超时（秒）

USE_PROXY  = False
PROXY_LIST = [
    # "http://user:pass@host:port",
    # "socks5://host:port",
]

USE_SELENIUM        = False  # JS 渲染 fallback
SELENIUM_HEADLESS   = True
SELENIUM_WAIT_SECONDS = 5

# ── User-Agent 池 ─────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ── 论文结构关键词映射 ────────────────────────
SECTION_KEYWORDS = {
    "abstract":     ["abstract", "summary"],
    "introduction": ["introduction", "background", "overview"],
    "related_work": ["related work", "prior work", "literature review"],
    "methodology":  ["methodology", "method", "approach", "model",
                     "framework", "system", "architecture", "proposed"],
    "experiments":  ["experiment", "evaluation", "result", "benchmark",
                     "dataset", "setup", "implementation"],
    "discussion":   ["discussion", "analysis", "ablation"],
    "conclusion":   ["conclusion", "concluding", "future work", "limitation"],
    "references":   ["references", "bibliography"],
}

# ── 日志 ──────────────────────────────────────
LOG_LEVEL   = "INFO"   # DEBUG / INFO / WARNING / ERROR
LOG_TO_FILE = True
