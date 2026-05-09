# modules/polisher.py — 模块6：论文润色（验收复用出口）
#
# 职责：读取已生成的风格模板，对用户的论文段落按目标风格改写
# 输出：润色后正文 + 修改说明 + 风格匹配评分 + 对比报告
# ─────────────────────────────────────────────────────────────────

import re
import json
import logging
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── Prompt 构建 ───────────────────────────────

def _build_polish_prompt(raw_text: str, template: dict) -> str:
    """
    将风格模板注入 Prompt，让 Claude 按该风格对原文改写
    只提取最关键的特征，控制 token 消耗
    """
    # 句式模板摘要（每章节前 3 条）
    patterns_lines = []
    for sec, pats in template.get("sentence_patterns", {}).items():
        for p in pats[:3]:
            if isinstance(p, dict) and p.get("pattern"):
                patterns_lines.append(f"  [{sec}] {p['pattern']}")

    top_phrases = list(template.get("vocabulary", {})
                       .get("academic_phrases", {}).keys())[:12]
    top_hedges  = list(template.get("hedging_language", {}).keys())[:8]
    summaries   = template.get("style_summaries", [])[:3]
    pv          = template.get("passive_voice_overall", "medium")

    style_block = f"""## 目标风格规则（来自已提取的论文模板）

### 代表性句式模板:
{chr(10).join(patterns_lines) or '  （无）'}

### 高频学术短语:
  {', '.join(top_phrases) or '（无）'}

### 学术限定语习惯:
  {', '.join(top_hedges) or '（无）'}

### 被动语态倾向: {pv}

### 风格描述:
{chr(10).join(f'  - {s}' for s in summaries) or '  （无）'}"""

    return f"""You are an expert academic writing editor.
Rewrite the following academic text to match the specific writing style described below.

{style_block}

---

## 原始文本（待润色）:
<original>
{raw_text}
</original>

---

## 润色要求:
1. **保持原意** — 不增删核心论点，只改写表达
2. **应用目标风格** — 使用上述句式模板、学术短语和限定语
3. **被动语态比例** 符合 "{pv}" 水平
4. **段落衔接自然**，逻辑递进清晰
5. **语言纯净**，避免口语化，确保学术正式度

## 严格按以下结构输出（不要省略任何分隔线）:

### POLISHED TEXT
（直接输出润色后的正文，不加注释）

---

### CHANGES SUMMARY
（中文，3~5 条，格式："原表达 → 改后表达：原因"）

---

### STYLE MATCH SCORE
（中文，1~10 分，说明匹配程度及不足之处）"""


# ── 核心润色函数 ──────────────────────────────

def polish_text(raw_text: str,
                template_json_path: str | Path,
                template_md_path:   str | Path = None) -> dict:
    """
    使用风格模板润色原始文本

    参数:
        raw_text           - 用户提供的待润色段落
        template_json_path - 模板 JSON 路径（extract 阶段生成）
        template_md_path   - 模板 MD 路径（可选，供日志参考）

    返回:
        {
          "polished_text":     str,   # 润色后正文
          "changes_summary":   str,   # 修改说明（中文）
          "style_match_score": str,   # 风格匹配评分
          "raw_text":          str,   # 原始文本（对比用）
          "full_response":     str,   # Claude 完整回复
        }
    """
    template_json_path = Path(template_json_path)
    if not template_json_path.exists():
        raise FileNotFoundError(f"模板文件不存在: {template_json_path}")

    template = json.loads(template_json_path.read_text(encoding="utf-8"))
    logger.info(f"[Polisher] 模板: {template_json_path.name}")
    logger.info(f"[Polisher] 原文长度: {len(raw_text)} 字符")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = _build_polish_prompt(raw_text, template)

    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_MAX_TOKENS,
        temperature=0.4,      # 稍高温度让润色更自然
        messages=[{"role": "user", "content": prompt}],
    )

    full = resp.content[0].text
    logger.info("[Polisher] 润色完成")
    return _parse_response(full, raw_text)


def _parse_response(response: str, raw_text: str) -> dict:
    """解析 Claude 结构化润色输出"""
    def _section(label: str) -> str:
        pat = rf"###\s*{re.escape(label)}\s*\n(.*?)(?=\n---|\n###|$)"
        m   = re.search(pat, response, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    polished = _section("POLISHED TEXT")
    changes  = _section("CHANGES SUMMARY")
    score    = _section("STYLE MATCH SCORE")

    # 解析失败保底：取前半段文本
    if not polished:
        lines    = response.strip().split("\n")
        polished = "\n".join(lines[:max(3, len(lines) // 2)])

    return {
        "polished_text":     polished,
        "changes_summary":   changes,
        "style_match_score": score,
        "raw_text":          raw_text,
        "full_response":     response,
    }


# ── 报告渲染 ──────────────────────────────────

def render_polish_report(result: dict, output_path: Path = None) -> str:
    """
    将润色结果渲染为 Markdown 对比报告
    原文 | 润色后 | 修改说明 | 评分
    """
    lines = [
        "# 论文润色报告",
        "",
        "---",
        "",
        "## 📄 原始文本",
        "",
        "```",
        result["raw_text"],
        "```",
        "",
        "---",
        "",
        "## ✨ 润色后文本",
        "",
        result["polished_text"],
        "",
        "---",
        "",
        "## 📝 主要修改说明",
        "",
        result["changes_summary"] or "（无）",
        "",
        "---",
        "",
        "## 🎯 风格匹配评分",
        "",
        result["style_match_score"] or "（无）",
        "",
    ]

    md = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md, encoding="utf-8")
        logger.info(f"[Polisher] 报告已保存: {output_path}")

    return md
