# modules/extractor.py — 模块2：正文提取 + 论文结构识别
#
# 职责：从 HTML 或 PDF 字节中提取结构化论文内容
# 输出：{"title", "abstract", "sections": [{"title", "section_type", "content"}]}
# ─────────────────────────────────────────────────────────────────

import re
import io
import logging
from pathlib import Path

from bs4 import BeautifulSoup

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── HTML 提取 ─────────────────────────────────

def extract_from_html(html: str, source_url: str = "") -> dict:
    """
    从 HTML 字符串提取结构化论文内容
    按优先级尝试：arXiv HTML 格式 → 通用 h1/h2/h3 切分 → 降级全段落
    """
    logger.info("[Extractor] 解析 HTML")
    soup = BeautifulSoup(html, "html.parser")

    # 去除噪声标签
    for tag in soup.find_all(["nav", "header", "footer", "script",
                               "style", "noscript", "aside"]):
        tag.decompose()
    for sup in soup.find_all("sup"):   # 脚注引用编号
        sup.decompose()

    result = {"title": _extract_title(soup), "abstract": "",
              "sections": [], "source_url": source_url}

    if _is_arxiv_html(soup):
        logger.info("[Extractor] arXiv HTML 格式")
        result.update(_parse_arxiv_html(soup))
    else:
        result.update(_parse_generic_html(soup))

    logger.info(f"[Extractor] 完成，{len(result['sections'])} 个章节")
    return result


def _is_arxiv_html(soup) -> bool:
    return bool(
        soup.find("article", class_=re.compile(r"ltx_document")) or
        soup.find("div", class_="ltx_abstract")
    )


def _parse_arxiv_html(soup) -> dict:
    abstract = ""
    ab = soup.find("div", class_="ltx_abstract")
    if ab:
        abstract = _clean(ab.get_text())

    sections = []
    for sec in soup.find_all("section", class_=re.compile(r"ltx_section")):
        h = sec.find(["h2", "h3", "h4"])
        title = _clean(h.get_text()) if h else "Untitled"
        if _match_type(title) == "references":
            continue
        paras = [_clean(p.get_text()) for p in sec.find_all("p")
                 if len(p.get_text().strip()) > 50]
        content = "\n\n".join(paras)
        if content:
            sections.append({"title": title, "section_type": _match_type(title),
                              "content": content})
    return {"abstract": abstract, "sections": sections}


def _parse_generic_html(soup) -> dict:
    abstract = ""
    for el in (soup.find_all(attrs={"class": re.compile(r"abstract", re.I)}) +
               soup.find_all(attrs={"id":    re.compile(r"abstract", re.I)})):
        abstract = _clean(el.get_text())
        break

    sections = []
    for heading in soup.find_all(["h1", "h2", "h3"]):
        title = _clean(heading.get_text())
        if not title or len(title) > 120:
            continue
        paras, sibling = [], heading.find_next_sibling()
        while sibling:
            if sibling.name in ["h1", "h2", "h3"]:
                break
            if sibling.name == "p":
                t = _clean(sibling.get_text())
                if len(t) > 40:
                    paras.append(t)
            sibling = sibling.find_next_sibling()
        content = "\n\n".join(paras)
        sec_type = _match_type(title)
        if sec_type != "references" and content:
            sections.append({"title": title, "section_type": sec_type, "content": content})

    return {"abstract": abstract, "sections": sections}


# ── PDF 提取 ──────────────────────────────────

def extract_from_pdf(pdf_bytes: bytes) -> dict:
    """
    从 PDF 字节流提取文本并识别论文结构
    依赖 pdfplumber，仅支持有文字层的 PDF（非扫描件）
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("[Extractor] 请安装: pip install pdfplumber")
        return _empty()

    logger.info("[Extractor] 解析 PDF")
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        logger.info(f"[Extractor] {len(pdf.pages)} 页")
        for page in pdf.pages:
            t = page.extract_text(x_tolerance=2, y_tolerance=3)
            if t:
                pages.append(t)

    return _parse_text_by_headings("\n".join(pages))


def _parse_text_by_headings(text: str) -> dict:
    """纯文本按启发式规则识别标题，切分章节"""
    heading_re = re.compile(
        r"^(\d+\.?\d*\.?\s+[A-Z][A-Za-z\s]+|[A-Z][A-Z\s]{3,50})$")
    lines = text.split("\n")
    sections, abstract = [], ""
    cur_title, cur_paras = "Preamble", []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if heading_re.match(line) and len(line) < 80:
            if cur_paras:
                content  = "\n\n".join(cur_paras)
                sec_type = _match_type(cur_title)
                if sec_type == "abstract":
                    abstract = content
                elif sec_type != "references" and content:
                    sections.append({"title": cur_title, "section_type": sec_type,
                                     "content": content})
            cur_title, cur_paras = _clean(line), []
        else:
            if cur_paras and len(cur_paras[-1]) < 200:
                cur_paras[-1] += " " + line
            else:
                cur_paras.append(line)

    if cur_paras and _match_type(cur_title) != "references":
        sections.append({"title": cur_title, "section_type": _match_type(cur_title),
                         "content": "\n\n".join(cur_paras)})

    logger.info(f"[Extractor] PDF 提取完成，{len(sections)} 个章节")
    return {"title": sections[0]["content"][:80] if sections else "",
            "abstract": abstract, "sections": sections, "source_url": ""}


# ── 工具 ──────────────────────────────────────

def _extract_title(soup) -> str:
    if soup.title:
        return _clean(soup.title.get_text())
    h1 = soup.find("h1")
    if h1:
        return _clean(h1.get_text())
    el = soup.find(attrs={"class": re.compile(r"\btitle\b", re.I)})
    return _clean(el.get_text()) if el else "Unknown Title"


def _match_type(title: str) -> str:
    tl = title.lower()
    for sec_type, kws in config.SECTION_KEYWORDS.items():
        if any(kw in tl for kw in kws):
            return sec_type
    return "body"


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _empty() -> dict:
    return {"title": "", "abstract": "", "sections": [], "source_url": ""}
