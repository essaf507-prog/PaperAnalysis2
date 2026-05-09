# modules/template_generator.py — 模块5：风格模板聚合 + 生成
#
# 职责：汇总所有 chunk 的分析结果，生成可复用的写作风格模板
# 输出：Markdown 风格指南 + JSON 结构化模板
# ─────────────────────────────────────────────────────────────────

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── 特征聚合 ──────────────────────────────────

def aggregate_features(analyzed_chunks: List[dict]) -> Dict:
    """
    从所有 chunk 的 style_analysis 中聚合共同风格特征

    返回包含如下键的字典：
      sentence_patterns, vocabulary, logic_connectors,
      hedging_language, citation_patterns,
      passive_voice_overall, style_summaries, paragraph_strategies
    """
    valid = [c for c in analyzed_chunks if c.get("style_analysis")]
    if not valid:
        logger.warning("[Template] 无有效分析结果")
        return {}

    logger.info(f"[Template] 聚合 {len(valid)} 个 chunk 特征")

    # 按章节类型分组
    by_sec: Dict[str, list] = defaultdict(list)
    for c in valid:
        by_sec[c.get("section_type", "body")].append(c["style_analysis"])

    agg = {
        "sentence_patterns": {},
        "vocabulary": {
            "academic_phrases": Counter(),
            "transition_words": Counter(),
        },
        "logic_connectors": {
            "contrast":   Counter(),
            "addition":   Counter(),
            "causation":  Counter(),
            "concession": Counter(),
        },
        "hedging_language":   Counter(),
        "citation_patterns":  Counter(),
        "passive_voice":      [],
        "style_summaries":    [],
        "paragraph_strategies": defaultdict(list),
    }

    for sec_type, analyses in by_sec.items():
        raw_patterns = []

        for a in analyses:
            # 句式模板
            for p in a.get("sentence_patterns", []):
                if isinstance(p, dict) and p.get("pattern"):
                    raw_patterns.append(p)

            # 词汇
            vocab = a.get("vocabulary", {})
            for ph in vocab.get("academic_phrases", []):
                agg["vocabulary"]["academic_phrases"][ph] += 1
            for tw in vocab.get("transition_words", []):
                agg["vocabulary"]["transition_words"][tw] += 1

            # 逻辑连接词
            lc = a.get("logic_connectors", {})
            for cat in ["contrast", "addition", "causation", "concession"]:
                for w in lc.get(cat, []):
                    agg["logic_connectors"][cat][w] += 1

            # Hedging
            for h in a.get("hedging_language", []):
                agg["hedging_language"][h] += 1

            # 引用
            cs = a.get("citation_style", {})
            for ep in cs.get("embedding_patterns", []):
                agg["citation_patterns"][ep] += 1

            # 被动语态
            pv = a.get("passive_voice_ratio", "")
            if pv:
                agg["passive_voice"].append(pv)

            # 风格摘要
            sm = a.get("style_summary", "")
            if sm:
                agg["style_summaries"].append(f"[{sec_type}] {sm}")

            # 段落策略
            ps = a.get("paragraph_structure", {})
            if ps.get("opening_strategy"):
                agg["paragraph_strategies"][sec_type].append(ps["opening_strategy"])

        # 去重句式，按频率排序，最多保留 10 个/章节
        seen, unique = set(), []
        prio = {"common": 0, "occasional": 1, "rare": 2}
        for p in sorted(raw_patterns, key=lambda x: prio.get(x.get("frequency", "rare"), 2)):
            k = p["pattern"][:60]
            if k not in seen:
                seen.add(k)
                unique.append(p)
            if len(unique) >= 10:
                break
        agg["sentence_patterns"][sec_type] = unique

    pv_count = Counter(agg["passive_voice"])
    agg["passive_voice_overall"] = (
        pv_count.most_common(1)[0][0] if pv_count else "medium"
    )
    return agg


# ── Claude 二次归纳 ────────────────────────────

def generate_training_prompts(agg: dict, paper_title: str = "") -> str:
    """
    调用 Claude 对聚合特征进行二次归纳，生成可训练自己写作的 Prompt 模板集
    返回 Markdown 字符串
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    features_json = json.dumps({
        "sentence_patterns":   agg.get("sentence_patterns", {}),
        "top_academic_phrases": dict(
            agg["vocabulary"]["academic_phrases"].most_common(20)),
        "top_hedges":          dict(agg["hedging_language"].most_common(10)),
        "style_summaries":     agg.get("style_summaries", [])[:5],
        "passive_voice":       agg.get("passive_voice_overall", "medium"),
    }, ensure_ascii=False, indent=2)

    prompt = f"""Based on the writing style features extracted from the paper "{paper_title}",
generate a practical academic writing template guide in Markdown.

<style_features>
{features_json}
</style_features>

Include:
1. **Introduction Template** — 3 sentence-level patterns for problem/motivation
2. **Methodology Template** — 3 patterns for describing methods/models
3. **Results Template** — 3 patterns for presenting findings
4. **Conclusion Template** — 2 patterns for summarizing contributions

For each pattern: show the template with [PLACEHOLDER], explain when to use it, give a fill-in example.

Then add:
5. **Style Rules** — 5 bullet points: the most distinctive writing habits
6. **Training Prompt** — one Claude prompt to generate text in this exact style

Add Chinese annotations where helpful."""

    try:
        resp = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=config.CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}])
        return resp.content[0].text
    except Exception as e:
        logger.error(f"[Template] 生成训练 Prompt 失败: {e}")
        return ""


# ── Markdown 渲染 ──────────────────────────────

def render_markdown_template(agg: dict, training_prompts: str,
                              paper_title: str = "", source_url: str = "") -> str:
    """将聚合特征渲染为人类可读的 Markdown 风格指南"""
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 📝 论文写作风格模板",
        "",
        f"- **来源论文**: {paper_title or '未知'}",
        f"- **原始链接**: {source_url or '未知'}",
        f"- **生成时间**: {now}",
        "",
        "---",
        "",
        "## 一、句式模板库（按章节）",
        "",
    ]

    for sec_type, patterns in agg.get("sentence_patterns", {}).items():
        if not patterns:
            continue
        lines.append(f"### {sec_type.replace('_', ' ').title()}")
        lines.append("")
        for p in patterns:
            lines += [
                f"**模板**: `{p.get('pattern', '')}`  ",
                f"**用途**: {p.get('function', '')}  ",
                f"**示例**: _{p.get('example', '')}_  ",
                f"**频率**: {p.get('frequency', '')}  ",
                "",
            ]

    lines += ["---", "", "## 二、高频学术短语（Top 15）", ""]
    for phrase, cnt in agg["vocabulary"]["academic_phrases"].most_common(15):
        lines.append(f"- `{phrase}` （{cnt} 次）")
    lines.append("")

    lines += ["---", "", "## 三、逻辑连接词", ""]
    labels = {"contrast": "对比/转折", "addition": "递进/补充",
               "causation": "因果",    "concession": "让步"}
    for cat, label in labels.items():
        top = agg["logic_connectors"][cat].most_common(6)
        if top:
            lines.append(f"**{label}**: {'、'.join(f'`{w}`' for w, _ in top)}  ")
    lines.append("")

    lines += ["---", "", "## 四、学术限定语（Hedges）", ""]
    for h, _ in agg["hedging_language"].most_common(10):
        lines.append(f"- `{h}`")
    lines.append("")

    lines += [
        "---", "",
        "## 五、写作风格特征", "",
        f"- **被动语态程度**: {agg.get('passive_voice_overall', 'medium')}",
        "",
        "**风格描述**:", "",
    ]
    for sm in agg.get("style_summaries", [])[:4]:
        lines += [f"> {sm}", ""]

    if training_prompts:
        lines += ["---", "", "## 六、可复用训练模板与 Prompt", "", training_prompts, ""]

    lines += ["---", "",
              "_本文件由 Paper Style Extractor 自动生成，仅供学习研究使用_", ""]

    return "\n".join(lines)


# ── 保存 ──────────────────────────────────────

def save_template(markdown: str, agg: dict, paper_id: str) -> dict:
    """保存 Markdown + JSON 到 templates/ 目录，返回路径字典"""
    config.TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    md_path   = config.TEMPLATE_DIR / f"style_template_{paper_id}.md"
    json_path = config.TEMPLATE_DIR / f"style_template_{paper_id}.json"

    md_path.write_text(markdown, encoding="utf-8")
    logger.info(f"[Template] Markdown → {md_path}")

    # Counter / defaultdict 转为普通 dict 后序列化
    def _serial(obj):
        if isinstance(obj, Counter):
            return dict(obj)
        if isinstance(obj, defaultdict):
            return {k: (_serial(v) if not isinstance(v, str) else v)
                    for k, v in obj.items()}
        return obj

    json_path.write_text(
        json.dumps({k: _serial(v) for k, v in agg.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"[Template] JSON → {json_path}")
    return {"markdown_path": str(md_path), "json_path": str(json_path)}
