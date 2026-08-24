#!/usr/bin/env python3
"""
EITIA 报告部署脚本 — 一键串联：渲染 → 部署 → 构建 → 验证 → 交付

用法:
  python scripts/deploy_pdf.py data/report_data.json
  python scripts/deploy_pdf.py data/report_data.json --skip-verify  # 跳过 PDF 内容验证
  python scripts/deploy_pdf.py data/report_data.json --dry-run       # 干跑（不实际部署）

流程:
  Step 1: Jinja2 渲染（调用 render_report.py 内部渲染函数）
  Step 2: 复制渲染后的纯 HTML 到 Kami 模板目录
  Step 3: 调用 Kami build.py --verify eitia-cfr 生成 PDF
  Step 4: PDF 内容验证（检查是否还有 {{ }} Jinja2 残留标签）
  Step 5: 复制 PDF 到 D:/ClaudeCode/Report/
  Step 6: 恢复 Kami 模板目录中的 Jinja2 源文件（避免污染 Kami 模板库）

依赖:
  - jinja2 (pip install jinja2)
  - pypdf  (pip install pypdf)
  - Kami skill 已安装（build.py 可用）
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "assets"
EITIA_TEMPLATE = TEMPLATE_DIR / "eitia-cfr.html"

# Kami 安装目录（硬编码已知路径，减少寻找时间）
KAMI_BASE = Path(
    "C:/Users/周峰/AppData/Local/Claude-3p/local-agent-mode-sessions/"
    "skills-plugin/00000000-0000-4000-8000-000000000001/"
    "476080f2-c406-403a-a5e7-0e38045dded0/skills/kami"
)
KAMI_TEMPLATES = KAMI_BASE / "assets" / "templates"
KAMI_EXAMPLES = KAMI_BASE / "assets" / "examples"
KAMI_BUILD = KAMI_BASE / "scripts" / "build.py"

# 报告输出目录
_ENV_REPORT = os.environ.get("EITIA_REPORT_DIR", "")
if _ENV_REPORT:
    REPORT_DIR = Path(_ENV_REPORT)
elif Path("D:/ClaudeCode/Report").is_dir():
    REPORT_DIR = Path("D:/ClaudeCode/Report")
else:
    REPORT_DIR = SKILL_DIR / "reports"


def find_kami():
    """定位 Kami 安装目录"""
    if KAMI_BASE.exists() and KAMI_BUILD.exists():
        return True
    print("ERROR: 找不到 Kami 安装目录", file=sys.stderr)
    print(f"  预期位置: {KAMI_BASE}", file=sys.stderr)
    print("  请确认 Kami skill 已安装且 build.py 存在", file=sys.stderr)
    return False


def render_html(json_path):
    """Step 1: Jinja2 渲染 → 纯 HTML"""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
    )
    template = env.get_template("eitia-cfr.html")
    html = template.render(**data)

    # 检查渲染后是否仍有 Jinja2 残留
    residue = re.findall(r"\{\{[^}]*\}\}", html)
    if residue:
        print(f"ERROR: 渲染后仍残留 {len(residue)} 个 Jinja2 标签，渲染失败！", file=sys.stderr)
        for tag in residue[:5]:
            print(f"  - {tag}", file=sys.stderr)
        return None

    # 检查工具名泄漏
    from render_report import TOOL_LEAK_PATTERNS
    for pattern, replacement in TOOL_LEAK_PATTERNS:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            print(f"WARNING: 工具名泄漏: {len(matches)} 处 '{pattern}'", file=sys.stderr)

    return html


def deploy_to_kami(html):
    """Step 2: 复制渲染后的 HTML 到 Kami 模板目录"""
    if not KAMI_TEMPLATES.exists():
        KAMI_TEMPLATES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EITIA_TEMPLATE, str(KAMI_TEMPLATES / "eitia-cfr.html"))
    # 现在用渲染后的 HTML 覆盖
    deployed = KAMI_TEMPLATES / "eitia-cfr.html"
    with open(deployed, "w", encoding="utf-8") as f:
        f.write(html)
    return deployed


def restore_template():
    """Step 6: 恢复 Kami 模板目录中的 Jinja2 源文件"""
    shutil.copy2(str(EITIA_TEMPLATE), str(KAMI_TEMPLATES / "eitia-cfr.html"))


def build_pdf():
    """Step 3: 调用 Kami build.py 生成 PDF"""
    result = subprocess.run(
        [sys.executable, str(KAMI_BUILD), "--verify", "eitia-cfr"],
        capture_output=True, text=True, encoding="utf-8",
        timeout=120,
    )
    output = result.stdout + result.stderr
    if "OK: eitia-cfr:" in output:
        return True, output
    else:
        return False, output


def verify_pdf_content(pdf_path):
    """Step 4: 验证 PDF 内容——检查是否还有 Jinja2 残留"""
    try:
        from pypdf import PdfReader
    except ImportError:
        print("WARNING: pypdf 未安装，跳过 PDF 内容验证 (pip install pypdf)", file=sys.stderr)
        return True, "skipped"

    r = PdfReader(str(pdf_path))
    total_jinja = 0
    jinja_pages = []
    for i, page in enumerate(r.pages):
        text = page.extract_text()
        tags = re.findall(r"\{\{[^}]*\}\}", text)
        if tags:
            total_jinja += len(tags)
            jinja_pages.append((i + 1, tags[:3]))

    if total_jinja > 0:
        print(f"ERROR: PDF 中发现 {total_jinja} 个未渲染的 Jinja2 标签！", file=sys.stderr)
        for pg, tags in jinja_pages:
            print(f"  第 {pg} 页: {tags}", file=sys.stderr)
        return False, f"{total_jinja} Jinja2 tags found"
    else:
        return True, "0 Jinja tags"


def deliver_pdf(data, dry_run=False):
    """Step 5: 复制 PDF 到报告目录"""
    pdf_src = KAMI_EXAMPLES / "eitia-cfr.pdf"
    if not pdf_src.exists():
        print("ERROR: Kami 未生成 PDF 文件", file=sys.stderr)
        return None

    product = data["cover"]["product"].replace(" ", "_").replace("/", "-")[:30]
    version = data["appendix"]["version"]
    date_str = datetime.now().strftime("%Y%m%d")
    pdf_dst = REPORT_DIR / f"EITIA_{product}_{date_str}_{version}.pdf"

    if dry_run:
        print(f"[DRY-RUN] 将复制: {pdf_src} → {pdf_dst}")
        return pdf_dst

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(pdf_src), str(pdf_dst))
    return pdf_dst


def main():
    parser = argparse.ArgumentParser(description="EITIA 报告一键部署到 Kami 并生成 PDF")
    parser.add_argument("json_path", help="JSON 数据文件路径")
    parser.add_argument("--skip-verify", action="store_true", help="跳过 PDF 内容 Jinja2 残留检查")
    parser.add_argument("--dry-run", action="store_true", help="干跑模式（不实际部署/构建）")
    parser.add_argument("--skip-restore", action="store_true", help="跳过模板恢复（调试用）")
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        print(f"ERROR: JSON 文件不存在: {json_path}", file=sys.stderr)
        sys.exit(1)

    if not find_kami():
        sys.exit(1)

    print("=" * 60)
    print("EITIA 报告部署脚本")
    print("=" * 60)

    # Step 1: 渲染
    print("\n[1/6] Jinja2 渲染...")
    html = render_html(json_path)
    if html is None:
        sys.exit(1)
    print(f"  渲染成功: {len(html):,} 字节, 0 Jinja 残留")

    if args.dry_run:
        print("\n[DRY-RUN] 跳过后续步骤")
        return

    # Step 2: 部署
    print("\n[2/6] 部署到 Kami 模板目录...")
    deployed = deploy_to_kami(html)
    print(f"  已部署: {deployed}")

    # Step 3: 构建
    print("\n[3/6] Kami 构建 PDF...")
    ok, output = build_pdf()
    if not ok:
        print(f"ERROR: Kami 构建失败:\n{output}", file=sys.stderr)
        restore_template()
        sys.exit(1)
    print("  Kami 构建成功")

    # Step 4: 验证
    if not args.skip_verify:
        print("\n[4/6] PDF 内容验证...")
        pdf_path = KAMI_EXAMPLES / "eitia-cfr.pdf"
        ok, msg = verify_pdf_content(pdf_path)
        if not ok:
            restore_template()
            sys.exit(1)
        print(f"  验证通过: {msg}")

    # Step 5: 交付
    print("\n[5/6] 交付 PDF...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    delivered = deliver_pdf(data)
    if delivered:
        size_kb = delivered.stat().st_size / 1024
        print(f"  已交付: {delivered} ({size_kb:.0f} KB)")

    # Step 6: 恢复
    if not args.skip_restore:
        print("\n[6/6] 恢复 Kami 模板...")
        restore_template()
        print("  模板已恢复为 Jinja2 源文件")

    print("\n" + "=" * 60)
    print("部署完成！")
    print(f"  PDF: {delivered}")
    print("=" * 60)


if __name__ == "__main__":
    main()
