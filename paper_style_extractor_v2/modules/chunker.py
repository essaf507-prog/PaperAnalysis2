# modules/chunker.py — 模块3：语义分块（Chunking）
#
# 职责：将论文章节切分为适合 LLM 处理的 chunk
# 策略：段落边界优先 + 句子边界兜底 + 滑动重叠保留上下文
# ─────────────────────────────────────────────────────────────────

import re
import logging
from pathlib import Path
from typing import List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


def _tokens(text: str) -> int:
    """粗估 token 数（1 token ≈ 4 字符），无需加载 tokenizer"""
    return max(1, len(text) // 4)


def _split_paragraphs(text: str) -> List[str]:
    """按双换行切分段落，过滤过短片段"""
    return [p.strip() for p in re.split(r"\n\s*\n", text)
            if len(p.strip()) >= 20]


def _split_sentences(para: str, max_tokens: int) -> List[str]:
    """对超长段落按句子边界进一步切分，避免句中截断"""
    sentences = re.split(r"(?<=[.!?])\s+", para)
    chunks, cur = [], ""
    for sent in sentences:
        candidate = (cur + " " + sent).strip()
        if _tokens(candidate) <= max_tokens:
            cur = candidate
        else:
            if cur:
                chunks.append(cur)
            if _tokens(sent) > max_tokens:
                # 单句仍超长：按字符强制截断（保底）
                limit = max_tokens * 4
                while sent:
                    chunks.append(sent[:limit])
                    sent = sent[limit:]
            else:
                cur = sent
    if cur:
        chunks.append(cur)
    return chunks


def chunk_section(section: dict, chunk_size: int = None,
                  chunk_overlap: int = None) -> List[dict]:
    """
    对单个章节进行分块

    返回:
        [{"chunk_id": -1, "section_title", "section_type", "text", "tokens"}]
        chunk_id 由 chunk_paper() 统一编号
    """
    chunk_size    = chunk_size    or config.CHUNK_SIZE
    chunk_overlap = chunk_overlap or config.CHUNK_OVERLAP
    title         = section.get("title", "Unknown")
    sec_type      = section.get("section_type", "body")
    content       = section.get("content", "").strip()

    if not content:
        return []

    paragraphs  = _split_paragraphs(content)
    raw_chunks  = []
    cur         = ""

    for para in paragraphs:
        if _tokens(para) > chunk_size:
            # 段落本身超长，先按句子拆
            for sub in _split_sentences(para, chunk_size):
                candidate = (cur + "\n\n" + sub).strip()
                if _tokens(candidate) <= chunk_size:
                    cur = candidate
                else:
                    if cur:
                        raw_chunks.append(cur)
                    cur = sub
        else:
            candidate = (cur + "\n\n" + para).strip()
            if _tokens(candidate) <= chunk_size:
                cur = candidate
            else:
                if cur:
                    raw_chunks.append(cur)
                cur = para

    if cur:
        raw_chunks.append(cur)

    # 添加滑动重叠：将上一块末尾追加到当前块开头
    overlap_chars = chunk_overlap * 4
    final = []
    for i, text in enumerate(raw_chunks):
        if i > 0 and chunk_overlap > 0:
            tail = raw_chunks[i - 1][-overlap_chars:]
            m    = re.search(r"(?<=[.!?])\s+", tail)   # 从句子边界开始
            tail = tail[m.end():] if m else tail
            text = tail.strip() + " " + text

        tok = _tokens(text)
        # 过短 chunk 合并到下一块
        if tok < config.MIN_CHUNK_TOKENS and i < len(raw_chunks) - 1:
            raw_chunks[i + 1] = text + "\n\n" + raw_chunks[i + 1]
            continue

        final.append({"chunk_id": -1, "section_title": title,
                      "section_type": sec_type,
                      "text": text.strip(), "tokens": tok})

    logger.debug(f"[Chunker] '{title}' → {len(final)} chunk(s)")
    return final


def chunk_paper(paper: dict) -> List[dict]:
    """
    对整篇论文分块（摘要 + 所有章节），全局编号

    参数:
        paper — extract_from_html / extract_from_pdf 的返回值
    返回:
        全局 chunk_id 从 1 递增的列表
    """
    all_chunks, cid = [], 1

    # 摘要单独处理
    abstract = paper.get("abstract", "").strip()
    if len(abstract) > 50:
        for c in chunk_section({"title": "Abstract",
                                  "section_type": "abstract",
                                  "content": abstract}):
            c["chunk_id"] = cid
            all_chunks.append(c)
            cid += 1

    for sec in paper.get("sections", []):
        for c in chunk_section(sec):
            c["chunk_id"] = cid
            all_chunks.append(c)
            cid += 1

    total_tok = sum(c["tokens"] for c in all_chunks)
    logger.info(f"[Chunker] {len(all_chunks)} chunks，约 {total_tok} tokens")
    return all_chunks
