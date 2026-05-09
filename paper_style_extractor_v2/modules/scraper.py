# modules/scraper.py — 模块1：网页爬虫 + 反爬策略
#
# 职责：接收目标论文 URL，返回 HTML 字符串或 PDF 字节流
# 反爬：UA 轮换、随机延迟、指数退避重试、代理池、Selenium fallback
# ─────────────────────────────────────────────────────────────────

import random
import time
import logging
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── 内部工具 ──────────────────────────────────

def _random_delay():
    """随机休眠，模拟人工浏览间隔"""
    delay = random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX)
    logger.debug(f"[Scraper] 延迟 {delay:.2f}s")
    time.sleep(delay)


def _random_headers() -> dict:
    """随机 User-Agent + 常规浏览器请求头"""
    return {
        "User-Agent":               random.choice(config.USER_AGENTS),
        "Accept":                   "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":          "en-US,en;q=0.9",
        "Accept-Encoding":          "gzip, deflate, br",
        "Connection":               "keep-alive",
        "Upgrade-Insecure-Requests":"1",
        "Cache-Control":            "max-age=0",
    }


def _build_session() -> requests.Session:
    """带重试策略的 Session（5xx 自动退避重试）"""
    session = requests.Session()
    retry = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=config.RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)

    if config.USE_PROXY and config.PROXY_LIST:
        proxy = random.choice(config.PROXY_LIST)
        session.proxies = {"http": proxy, "https": proxy}
        logger.info(f"[Scraper] 使用代理: {proxy}")

    return session


def _check_robots(url: str) -> bool:
    """检查 robots.txt，返回 True 表示允许爬取"""
    parsed   = urlparse(url)
    rp       = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        rp.read()
        allowed = rp.can_fetch("*", url)
        if not allowed:
            logger.warning(f"[Scraper] robots.txt 禁止访问: {url}")
        return allowed
    except Exception as e:
        logger.warning(f"[Scraper] robots.txt 读取失败（保守放行）: {e}")
        return True


# ── 核心函数 ──────────────────────────────────

def fetch_html(url: str, respect_robots: bool = True) -> str | None:
    """
    爬取目标 URL 的 HTML 内容

    返回 HTML 字符串，失败返回 None
    """
    logger.info(f"[Scraper] 爬取 HTML: {url}")

    if respect_robots and not _check_robots(url):
        logger.error("[Scraper] robots.txt 禁止，终止")
        return None

    session = _build_session()

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            _random_delay()
            resp = session.get(url, headers=_random_headers(),
                               timeout=config.REQUEST_TIMEOUT, allow_redirects=True)

            if resp.status_code == 200:
                logger.info(f"[Scraper] 成功，{len(resp.text)} 字符")
                return resp.text

            elif resp.status_code == 403:
                logger.warning(f"[Scraper] 403 Forbidden（尝试 {attempt}）")
                if config.USE_SELENIUM:
                    return _fetch_selenium(url)
                break

            elif resp.status_code == 429:
                wait = config.RETRY_BACKOFF ** attempt * 5
                logger.warning(f"[Scraper] 429 限速，等待 {wait:.0f}s")
                time.sleep(wait)

            else:
                logger.warning(f"[Scraper] HTTP {resp.status_code}（尝试 {attempt}）")

        except requests.exceptions.Timeout:
            logger.warning(f"[Scraper] 超时（尝试 {attempt}）")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"[Scraper] 连接错误（尝试 {attempt}）: {e}")
        except Exception as e:
            logger.exception(f"[Scraper] 异常（尝试 {attempt}）: {e}")

        time.sleep(config.RETRY_BACKOFF ** attempt)

    logger.error(f"[Scraper] 全部重试失败: {url}")
    return None


def fetch_pdf_bytes(url: str) -> bytes | None:
    """下载 PDF 原始字节，失败返回 None"""
    logger.info(f"[Scraper] 下载 PDF: {url}")
    session = _build_session()
    try:
        _random_delay()
        resp = session.get(url, headers=_random_headers(),
                           timeout=config.REQUEST_TIMEOUT * 2, stream=True)
        if resp.status_code == 200:
            data = resp.content
            logger.info(f"[Scraper] PDF 下载成功，{len(data)/1024:.1f} KB")
            return data
        logger.error(f"[Scraper] PDF 下载失败 HTTP {resp.status_code}")
    except Exception as e:
        logger.exception(f"[Scraper] PDF 异常: {e}")
    return None


def _fetch_selenium(url: str) -> str | None:
    """Selenium fallback，处理 JS 渲染页面（需安装 selenium + webdriver-manager）"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        logger.info(f"[Scraper] Selenium 模式: {url}")
        opts = Options()
        if config.SELENIUM_HEADLESS:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"--user-agent={random.choice(config.USER_AGENTS)}")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=opts)
        try:
            driver.get(url)
            time.sleep(config.SELENIUM_WAIT_SECONDS)
            html = driver.page_source
            logger.info(f"[Scraper] Selenium 成功，{len(html)} 字符")
            return html
        finally:
            driver.quit()
    except ImportError:
        logger.error("[Scraper] Selenium 未安装: pip install selenium webdriver-manager")
    except Exception as e:
        logger.exception(f"[Scraper] Selenium 异常: {e}")
    return None


def resolve_arxiv_url(url: str) -> dict:
    """
    从任意 arXiv URL 解析出 HTML / PDF / abs 三种链接

    输入:  https://arxiv.org/abs/2310.06825  （或 pdf/html 变体）
    输出:  {"html": ..., "pdf": ..., "abs": ..., "paper_id": "2310.06825"}
    """
    parts   = urlparse(url).path.strip("/").split("/")
    paper_id = None
    for part in parts:
        if part not in ("abs", "pdf", "html") and ("." in part or part.isdigit()):
            paper_id = part.replace(".pdf", "")
            break

    if not paper_id:
        logger.warning(f"[Scraper] 无法解析 arXiv ID: {url}")
        return {"html": url, "pdf": url, "abs": url, "paper_id": "unknown"}

    return {
        "html":     f"https://arxiv.org/html/{paper_id}",
        "pdf":      f"https://arxiv.org/pdf/{paper_id}",
        "abs":      f"https://arxiv.org/abs/{paper_id}",
        "paper_id": paper_id,
    }
