# modules/analyzer.py — 模块4：Claude 语义分析
#
# 职责：逐 chunk 调用 Claude API，分析写作风格特征
# 分析维度：句式 / 词汇 / 逻辑连接词 / 段落结构 / Hedging / 引用方式
# ─────────────────────────────────────────────────────────────────

import re
import json
import time
import logging
from pathlib import Path
from typing import List, Optional

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise ValueError("未设置 ANTHROPIC_API_KEY")
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ── Prompt ────────────────────────────────────

SYSTEM = (
    "You are an expert in academic writing style analysis. "
    "Analyze the given passage and extract reusable writing style features. "
    "Always respond with valid JSON only — no text outside the JSON object."
)


def _build_prompt(text: str, section_type: str) -> str:
    return f"""Analyze this academic paper excerpt from the "{section_type}" section.
Extract writing style patterns reusable as a writing template.

<excerpt>
{text}
</excerpt>

Return ONLY a JSON object with this structure:
{{
  "sentence_patterns": [
    {{
      "pattern": "template with [PLACEHOLDER] for key terms",
      "example": "original sentence from the text",
      "frequency": "common|occasional|rare",
      "function": "rhetorical purpose of this pattern"
    }}
  ],
  "vocabulary": {{
    "academic_phrases": ["3-6 word academic collocations found"],
    "transition_words": ["logical connectors used"],
    "domain_terms_style": "how domain terms are introduced"
  }},
  "logic_connectors": {{
    "contrast":   ["adversative words/phrases"],
    "addition":   ["additive connectors"],
    "causation":  ["causal connectors"],
    "concession": ["concessive phrases"]
  }},
  "paragraph_structure": {{
    "opening_strategy": "how paragraphs typically begin",
    "closing_strategy": "how paragraphs typically end",
    "avg_sentences_per_paragraph": "estimated number"
  }},
  "hedging_language": ["hedging expressions found"],
  "citation_style": {{
    "embedding_patterns": ["how citations are woven in"],
    "attribution_phrases": ["phrases used to attribute claims"]
  }},
  "passive_voice_ratio": "low|medium|high",
  "style_summary": "2-3 sentences on the distinctive writing style"
}}"""


# ── 核心函数 ──────────────────────────────────

def analyze_chunk(chunk: dict, retry: int = 2) -> dict:
    """
    对单个 chunk 进行风格分析，返回追加了 style_analysis 字段的 chunk
    失败时 style_analysis 为 None，不中断流程
    """
    cid      = chunk.get("chunk_id", "?")
    sec_type = chunk.get("section_type", "body")
    text     = chunk.get("text", "")

    logger.info(f"[Analyzer] chunk #{cid}（{sec_type}，~{chunk.get('tokens', 0)} tokens）")

    client = _get_client()
    prompt = _build_prompt(text, sec_type)

    for attempt in range(1, retry + 2):
        try:
            resp     = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=config.CLAUDE_MAX_TOKENS,
                temperature=config.CLAUDE_TEMPERATURE,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw      = resp.content[0].text.strip()
            # 去除可能的 markdown 代码块包裹
            raw      = re.sub(r"```(?:json)?", "", raw).strip("` \n")
            analysis = json.loads(raw)
            logger.debug(f"[Analyzer] chunk #{cid} 完成")
            return {**chunk, "style_analysis": analysis}

        except json.JSONDecodeError as e:
            logger.warning(f"[Analyzer] #{cid} JSON 解析失败（{attempt}）: {e}")
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            logger.warning(f"[Analyzer] Rate limit，等待 {wait}s")
            time.sleep(wait)
        except anthropic.APIError as e:
            logger.error(f"[Analyzer] API 错误（{attempt}）: {e}")
        except Exception as e:
            logger.exception(f"[Analyzer] 未知异常（{attempt}）: {e}")

        if attempt <= retry:
            time.sleep(2 ** attempt)

    logger.error(f"[Analyzer] chunk #{cid} 全部重试失败，已跳过")
    return {**chunk, "style_analysis": None}


def analyze_all_chunks(chunks: List[dict],
                       max_chunks: int = 0,
                       section_filter: List[str] = None) -> List[dict]:
    """
    批量分析 chunk 列表

    参数:
        max_chunks     - 0 = 全部；测试时建议 3~5
        section_filter - 只分析指定章节类型，None = 全部
    """
    targets = chunks
    if section_filter:
        targets = [c for c in chunks if c.get("section_type") in section_filter]
        logger.info(f"[Analyzer] 过滤后 {len(targets)} chunks（{section_filter}）")
    if max_chunks > 0:
        targets = targets[:max_chunks]
        logger.info(f"[Analyzer] 限制分析 {max_chunks} chunks")

    results = []
    total   = len(targets)
    for i, chunk in enumerate(targets, 1):
        logger.info(f"[Analyzer] 进度 {i}/{total}")
        results.append(analyze_chunk(chunk))
        if i < total:
            time.sleep(0.8)   # 限速保护

    ok = sum(1 for r in results if r.get("style_analysis"))
    logger.info(f"[Analyzer] 完成 {ok}/{total} 成功")
    return results
