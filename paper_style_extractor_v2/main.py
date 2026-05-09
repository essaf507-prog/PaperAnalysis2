# main.py — 主入口（双子命令：extract / polish）
#
# extract：爬取论文 → 提取分析 → 生成风格模板
# polish ：读取模板 → 润色用户文本 → 输出对比报告（验收复用出口）
#
# 用法:
#   python main.py extract --url "https://arxiv.org/abs/2310.06825"
#   python main.py polish  --text "your draft..."
#   python main.py polish  --file my_draft.txt
# ─────────────────────────────────────────────────────────────────

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from modules.scraper           import fetch_html, fetch_pdf_bytes, resolve_arxiv_url
from modules.extractor         import extract_from_html, extract_from_pdf
from modules.chunker           import chunk_paper
from modules.analyzer          import analyze_all_chunks
from modules.template_generator import (
    aggregate_features, generate_training_prompts,
    render_markdown_template, save_template,
)
from modules.polisher          import polish_text, render_polish_report


# ── 日志初始化 ────────────────────────────────

def setup_logging(label: str = "run") -> logging.Logger:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    handlers = [logging.StreamHandler(sys.stdout)]
    if config.LOG_TO_FILE:
        handlers.append(
            logging.FileHandler(config.LOG_DIR / f"{label}_{ts}.log",
                                encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=handlers, force=True,
    )
    return logging.getLogger("main")


# ── 工具函数 ──────────────────────────────────

def _paper_id(url: str) -> str:
    """URL → 安全文件名"""
    path = urlparse(url).path.strip("/").replace("/", "_")
    return re.sub(r"[^\w\-.]", "_", path)[-40:] or "paper"


def _save(data, path: Path, label: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    else:
        path.write_text(str(data), encoding="utf-8")
    logging.getLogger("main").info(f"[Output] {label} → {path}")


# ═══════════════════════════════════════════════
# STEP 流水线（extract 子命令）
# ═══════════════════════════════════════════════

def run_pipeline(url: str, output_dir: Path = None, max_chunks: int = 0,
                 section_filter: list = None, force_pdf: bool = False) -> dict:
    """
    完整执行：爬取 → 提取 → 分块 → 分析 → 生成模板

    返回: {"status": "success"|"error", "outputs": {...}, "stats": {...}}
    """
    pid    = _paper_id(url)
    logger = setup_logging(pid)
    outdir = output_dir or (config.OUTPUT_DIR / pid)
    outdir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("  Paper Style Extractor — extract")
    logger.info(f"  URL      : {url}")
    logger.info(f"  Paper ID : {pid}")
    logger.info(f"  输出目录 : {outdir}")
    logger.info("=" * 60)

    outputs = {}
    t0      = time.time()

    # ── STEP 1: 爬取 ──────────────────────────
    logger.info("\n【STEP 1】爬取论文页面")
    raw_html, pdf_bytes = None, None

    if "arxiv.org" in url and not force_pdf:
        arxiv  = resolve_arxiv_url(url)
        raw_html = fetch_html(arxiv["html"])
        if not raw_html:
            logger.warning("  arXiv HTML 失败，切换 PDF")
            pdf_bytes = fetch_pdf_bytes(arxiv["pdf"])
    elif url.lower().endswith(".pdf") or force_pdf:
        pdf_bytes = fetch_pdf_bytes(url)
    else:
        raw_html = fetch_html(url)

    if not raw_html and not pdf_bytes:
        logger.error("STEP 1 失败：无法获取内容")
        return {"status": "error", "message": "爬取失败", "paper_id": pid}

    if raw_html:
        p = outdir / "raw.html"
        _save(raw_html, p, "原始 HTML")
        outputs["raw_html"] = str(p)
    if pdf_bytes:
        p = outdir / "raw.pdf"
        p.write_bytes(pdf_bytes)
        outputs["raw_pdf"] = str(p)
    logger.info("STEP 1 ✓")

    # ── STEP 2: 提取结构 ──────────────────────
    logger.info("\n【STEP 2】提取论文结构")
    paper = (extract_from_html(raw_html, url) if raw_html
             else extract_from_pdf(pdf_bytes))

    if not paper.get("sections"):
        logger.error("STEP 2 失败：未提取到章节")
        return {"status": "error", "message": "提取失败", "paper_id": pid}

    logger.info(f"  标题   : {paper.get('title', '')[:80]}")
    logger.info(f"  摘要   : {len(paper.get('abstract', ''))} 字符")
    logger.info(f"  章节数 : {len(paper['sections'])}")
    for s in paper["sections"]:
        logger.info(f"    [{s['section_type']}] {s['title'][:60]}")

    p = outdir / "extracted.json"
    _save(paper, p, "结构化正文")
    outputs["extracted"] = str(p)
    logger.info("STEP 2 ✓")

    # ── STEP 3: 分块 ──────────────────────────
    logger.info("\n【STEP 3】文本分块")
    chunks = chunk_paper(paper)
    if not chunks:
        logger.error("STEP 3 失败：分块为空")
        return {"status": "error", "message": "分块失败", "paper_id": pid}

    logger.info(f"  {len(chunks)} chunks，约 {sum(c['tokens'] for c in chunks)} tokens")
    p = outdir / "chunks.json"
    _save(chunks, p, "分块结果")
    outputs["chunks"] = str(p)
    logger.info("STEP 3 ✓")

    # ── STEP 4: Claude 语义分析 ───────────────
    logger.info("\n【STEP 4】Claude 语义分析")
    if not config.ANTHROPIC_API_KEY:
        logger.error("未设置 ANTHROPIC_API_KEY")
        return {"status": "error", "message": "API Key 未配置", "paper_id": pid}

    analyzed = analyze_all_chunks(chunks, max_chunks=max_chunks,
                                   section_filter=section_filter)
    p = outdir / "analysis.json"
    _save(analyzed, p, "语义分析")
    outputs["analysis"] = str(p)
    logger.info("STEP 4 ✓")

    # ── STEP 5: 生成风格模板 ──────────────────
    logger.info("\n【STEP 5】生成风格模板")
    agg = aggregate_features(analyzed)
    if not agg:
        logger.error("STEP 5 失败：特征聚合为空")
        return {"status": "error", "message": "模板生成失败", "paper_id": pid}

    title    = paper.get("title", "")
    prompts  = generate_training_prompts(agg, title)
    markdown = render_markdown_template(agg, prompts, title, url)
    saved    = save_template(markdown, agg, pid)
    outputs.update({"template_md": saved["markdown_path"],
                    "template_json": saved["json_path"]})
    logger.info("STEP 5 ✓")

    # ── 验收摘要 ──────────────────────────────
    elapsed = time.time() - t0
    logger.info("\n" + "=" * 60)
    logger.info(f"  ✅ 全流程完成！耗时 {elapsed:.1f}s")
    logger.info("")
    logger.info("  📦 交付物清单:")
    for k, v in outputs.items():
        logger.info(f"    [{k}] {v}")
    logger.info("")
    logger.info(f"  🎯 核心交付物: {outputs.get('template_md', 'N/A')}")
    logger.info("=" * 60)

    return {
        "status":    "success",
        "paper_id":  pid,
        "paper_title": title,
        "outputs":   outputs,
        "stats": {
            "sections":        len(paper["sections"]),
            "chunks":          len(chunks),
            "analyzed_chunks": sum(1 for c in analyzed if c.get("style_analysis")),
            "elapsed_seconds": round(elapsed, 1),
        },
    }


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Paper Style Extractor — 学术论文风格提取与润色工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 第一步：爬取论文并生成风格模板
  python main.py extract --url "https://arxiv.org/abs/2310.06825"

  # 第二步：用模板润色自己的文稿（验收复用出口）
  python main.py polish --text "In this paper, we try to solve..."
  python main.py polish --file my_draft.txt
  python main.py polish --file my_draft.txt --template templates/style_template_xxx.json
        """,
    )
    parser.add_argument("--api-key", help="Claude API Key（覆盖环境变量）")
    subs = parser.add_subparsers(dest="command", required=True)

    # ── extract ───────────────────────────────
    ep = subs.add_parser("extract", help="爬取论文并生成风格模板")
    ep.add_argument("--url",        required=True, help="目标论文 URL")
    ep.add_argument("--output",     default=None,  help="中间产物目录")
    ep.add_argument("--max-chunks", type=int, default=0,
                    help="最多分析 N 个 chunk（0=全部；测试建议 3~5）")
    ep.add_argument("--sections",   nargs="+", default=None, metavar="TYPE",
                    help="只分析指定章节类型（introduction methodology conclusion ...）")
    ep.add_argument("--pdf",        action="store_true", help="强制 PDF 模式")

    # ── polish ────────────────────────────────
    pp = subs.add_parser("polish", help="用风格模板润色你的论文（验收复用出口）")
    src = pp.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="直接传入待润色文本")
    src.add_argument("--file", help="从 .txt 文件读取待润色文本")
    pp.add_argument("--template", default=None,
                    help="指定模板 JSON 路径（默认自动选 templates/ 下最新）")
    pp.add_argument("--output", default=None,
                    help="润色报告保存路径（默认 output/polish_report_<ts>.md）")

    args = parser.parse_args()

    if args.api_key:
        config.ANTHROPIC_API_KEY = args.api_key

    if args.command == "extract":
        _cmd_extract(args)
    elif args.command == "polish":
        _cmd_polish(args)


# ── extract 处理 ──────────────────────────────

def _cmd_extract(args):
    outdir = Path(args.output) if args.output else None
    result = run_pipeline(
        url=args.url, output_dir=outdir,
        max_chunks=args.max_chunks,
        section_filter=args.sections,
        force_pdf=args.pdf,
    )
    sys.exit(0 if result["status"] == "success" else 1)


# ── polish 处理 ───────────────────────────────

def _cmd_polish(args):
    logger = setup_logging("polish")

    # 1. 读取待润色文本
    if args.text:
        raw_text = args.text.strip()
    else:
        fp = Path(args.file)
        if not fp.exists():
            logger.error(f"文件不存在: {fp}")
            sys.exit(1)
        raw_text = fp.read_text(encoding="utf-8").strip()

    if not raw_text:
        logger.error("待润色文本为空")
        sys.exit(1)

    # 2. 定位风格模板
    tpl_path = None
    if args.template:
        tpl_path = Path(args.template)
    else:
        jsons = sorted(config.TEMPLATE_DIR.glob("style_template_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if jsons:
            tpl_path = jsons[0]
            logger.info(f"[Polish] 自动选用最新模板: {tpl_path.name}")
        else:
            logger.error(
                "未找到风格模板！请先运行:\n"
                "  python main.py extract --url <论文URL>\n"
                "或用 --template 指定模板路径")
            sys.exit(1)

    tpl_md_path = tpl_path.with_suffix(".md")

    # 3. 执行润色
    if not config.ANTHROPIC_API_KEY:
        logger.error("未设置 ANTHROPIC_API_KEY")
        sys.exit(1)

    logger.info("\n" + "=" * 60)
    logger.info("  ✏️  Paper Polisher — 开始润色")
    logger.info(f"  模板    : {tpl_path.name}")
    logger.info(f"  原文长度: {len(raw_text)} 字符")
    logger.info("=" * 60 + "\n")

    result = polish_text(raw_text, tpl_path, tpl_md_path)

    # 4. 控制台直接输出润色结果
    print("\n" + "=" * 60)
    print("  ✨ 润色结果")
    print("=" * 60 + "\n")
    print(result["polished_text"])
    print("\n" + "─" * 60)
    print("📝 主要修改说明:\n")
    print(result["changes_summary"])
    print("\n🎯 风格匹配评分:\n")
    print(result["style_match_score"])
    print("─" * 60)

    # 5. 保存润色报告（验收交付物）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = (Path(args.output) if args.output
                   else config.OUTPUT_DIR / f"polish_report_{ts}.md")
    render_polish_report(result, output_path=report_path)
    print(f"\n💾 完整报告已保存: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
