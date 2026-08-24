#!/usr/bin/env python3
r"""
EITIA 报告渲染器 — Jinja2 模板 + JSON 数据 → 完整 HTML

用法:
  python scripts/render_report.py data/report_data.json
  python scripts/render_report.py data/report_data.json --output report.html
  python scripts/render_report.py data/report_data.json --check-only

输出:
  D:\ClaudeCode\Report\EITIA_{产品}_{日期}_v{版本}.html

校验项 (V5 扩展):
  1. JSON 结构完整性（所有必填字段存在）
  2. L0 行业全景密度检查（5 项子组件）
  3. 匹配度诊断可追溯检查（sub_scores/raw_data/source）
  4. 采购推算公式检查（base_calc.formula/base_source）
  5. 脉脉来源检查（contact_cards 中是否有脉脉来源）
  6. Jinja2 渲染无异常
  7. 无残留 {{ 标记（Jinja2 未渲染的变量）
  8. 客户数 >= 1
  9. 每客户 8 个 section 的 HTML 内容非空
  10. 无 MCP 工具名泄漏
  11. 内容密度完整性检查
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, TemplateNotFound
except ImportError:
    print("ERROR: jinja2 未安装。运行: pip install jinja2")
    sys.exit(1)

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "assets"

# 报告输出目录（三级回退：环境变量 → 历史兼容 → 可移植默认）
_ENV_REPORT = os.environ.get("EITIA_REPORT_DIR", "")
if _ENV_REPORT:
    REPORT_DIR = Path(_ENV_REPORT)
elif Path("D:/ClaudeCode/Report").is_dir():
    REPORT_DIR = Path("D:/ClaudeCode/Report")
else:
    REPORT_DIR = SKILL_DIR / "reports"

# Docstrings now use raw prefix to avoid SyntaxWarning on backslash paths

# MCP 工具名泄漏检查正则（完整覆盖所有数据源）
TOOL_LEAK_PATTERNS = [
    # 内部脚本名/文件名（V5.4.1 新增）
    (
        r"score_calculator\.py|render_report\.py|deploy_pdf\.py|eitia-cfr\.html|dedup_manager\.py|maimai_search\.py",
        "系统内部工具",
    ),
    # 内部平台名（V5.4.1 新增）
    (r"\bmaimai\b|\bmaimai-prospect\b|\b脉脉\b", "公开职业社交平台"),
    # V5.4.2: 模板内部类名泄漏 — 禁止 df-step-card / df-step-role 等旧版 CSS 类出现在 JSON 数据的 HTML 块中
    # 决策链应使用新版类名：decision-flow / df-step / df-role / df-action / df-arrow
    (r"\bdf-step-card\b", "新版决策链使用 df-step 代替 df-step-card"),
    (r"\bdf-step-role\b", "新版决策链使用 df-role 代替 df-step-role"),
    # 填充文字检测
    (r"xxxx+[^;]|X{4,}|占位|待填|placeholder|\[TBD\]|\[TODO\]", "填充文字/占位符（报告不完整）"),
    # 搜索引擎
    (r"bocha|bocha_web_search|bocha_ai_search", "行业公开搜索"),
    (r"tavily|tavily_search|tavily_extract|tavily_crawl", "行业公开搜索"),
    (r"exa\b|web_search_exa|web_fetch_exa", "行业公开搜索"),
    (r"anys earch|anys earch_web|anys earch_extract", "行业公开搜索"),
    (r"tinyfish|fetch_content|run_web_automation|batch_create", "行业公开搜索"),
    # 天眼查工具名
    (r"tyc-mcp|tianyancha|天眼查", "企业公开登记信息"),
    (r"call_tool(?!s)", "企业公开登记信息"),
    (r"get_company_basic_profile", "企业公开登记信息"),
    (r"get_company_capabilities", "企业公开登记信息"),
    (r"get_company_group_profile", "企业公开登记信息"),
    (r"get_company_people", "企业公开登记信息"),
    (r"get_suppliers_and_customers", "企业公开登记信息"),
    (r"get_financing_records", "企业公开登记信息"),
    (r"get_products_info", "企业公开登记信息"),
    (r"get_recruitment_info", "企业公开登记信息"),
    (r"get_bidding_info", "企业公开登记信息"),
    (r"get_risk_overview", "企业公开登记信息"),
    (r"get_relation_graph|get_relation_path", "企业公开登记信息"),
    (r"get_patent_info", "企业公开登记信息"),
    (r"get_shareholder_info", "企业公开登记信息"),
    (r"search_companies", "企业公开搜索"),
    (r"search_listed_companies|search_patents|search_trademarks", "企业公开搜索"),
    # 企查查工具名
    (
        r"qcc-mcp|qcc-company|qcc-risk|qcc-ipr|qcc-operation|qcc-executive|qcc-history",
        "企业公开信用信息系统",
    ),
    (r"get_company_registration_info", "企业公开信用信息系统"),
    (r"get_company_risk_scan", "企业公开信用信息系统"),
    (r"get_credit_evaluation", "企业公开信用信息系统"),
    (r"get_contact_info", "企业公开信用信息系统"),
    (r"get_key_personnel", "企业公开信用信息系统"),
    (r"get_actual_controller", "企业公开信用信息系统"),
    (r"get_external_investments", "企业公开信用信息系统"),
    (r"get_judicial_documents|get_case_filing_info", "企业公开信用信息系统"),
    (r"get_dishonest_info|get_judgment_debtor_info", "企业公开信用信息系统"),
    (r"get_news_sentiment", "公开新闻信息"),
    # 金融数据工具名
    (r"eastmoney|mx_ds_mcp|mx_ashare|mx_finance|mx_stocks_screener", "公开市场信息"),
    (r"tushareMcp|tushare\b", "公开市场信息"),
    (r"adj_factor|daily_basic|income|balancesheet|cashflow", "公开市场信息"),
    # 其他
    (r"playwright|browser_|preview_", "浏览器辅助工具"),
    # 其他
    (r"playwright|browser_|preview_", "浏览器辅助工具"),
    (r"bazhuayu", "数据采集"),
    (r"bazhuayu", "数据采集"),
]

# 必填字段schema（V5 扩展 — 递归检查）
# V5.3: 八维标准名称（用于维度名称一致性检查）
STANDARD_LABELS = [
    "采购规模",
    "技术匹配",
    "需求强度",
    "采购时机",
    "竞争位置",
    "触达可行",
    "决策复杂度",
    "信用安全",
]

REQUIRED_FIELDS = {
    "": ["cover", "l0", "clients", "appendix"],
    "cover": [
        "title",
        "subtitle",
        "product",
        "scope",
        "date",
        "data_date",
        "summary",
        "company_name",
    ],
    # V5: l0.industry 结构化体（替代旧版 l0.industry_overview HTML 块）
    "l0": ["funnel", "signal_heatmap", "top_table", "top_n"],
    "l0_industry": [
        "market_size",
        "eitia_position",
        "customer_map",
        "competitive_landscape",
        "key_trends",
    ],
    "client": [
        "fullname",
        "display_name",
        "score",
        "rank",
        "tags",
        "kpi_row",
        "oneliner",
        "basic_table",
        "equity_section",
        "match_highlights",
        "match_risks",
        "veto_check",
        "contacts_intro",
        "decision_insight",
        "decision_chain",
        "signal_insight",
    ],
    "client_sub": [
        "match_subscore_1",
        "match_subscore_2",
        "match_subscore_3",
        "match_subscore_4",
        "match_subscore_5",
        "match_subscore_6",
        "match_subscore_7",
        "match_subscore_8",
        "procurement",
        "contact_cards",
        "signals",
        "engagement",
        "competition",
        "risks",
    ],
    "appendix": ["data_log", "scoring_method", "glossary", "disclaimer", "version"],
}


def validate_json(data):
    # 验证 JSON 数据完整性，返回错误列表
    errors = []

    # 顶层字段
    for field in REQUIRED_FIELDS[""]:
        if field not in data:
            errors.append(f"缺少顶层字段: {field}")

    # 封面字段
    cover = data.get("cover", {})
    for field in REQUIRED_FIELDS["cover"]:
        if field not in cover:
            errors.append(f"cover 缺少字段: {field}")

    # L0 字段
    l0 = data.get("l0", {})
    for field in REQUIRED_FIELDS["l0"]:
        if field not in l0:
            errors.append(f"l0 缺少字段: {field}")

    # V5: L0 行业全景结构化检查
    industry = l0.get("industry", {})
    if industry:
        for field in REQUIRED_FIELDS["l0_industry"]:
            if field not in industry:
                errors.append(f"l0.industry 缺少字段: {field}")
        # 子字段内容检查 — V5.4: market_size 支持新旧两种格式
        ms = industry.get("market_size", {})
        if isinstance(ms, dict):
            has_amount = ms.get("amount") and str(ms.get("amount", "")).strip()
            has_value = "value" in ms and str(ms.get("value", "")).strip()
            if not has_amount and not has_value:
                errors.append("l0.industry.market_size 缺少 amount 或 value 字段")
        cm = industry.get("customer_map", [])
        if not isinstance(cm, list) or len(cm) < 3:
            errors.append(
                f"l0.industry.customer_map 不足（当前{len(cm) if isinstance(cm, list) else 0}条，需>=3）"
            )
        cl = industry.get("competitive_landscape", [])
        if not isinstance(cl, list) or len(cl) < 3:
            errors.append(
                f"l0.industry.competitive_landscape 不足（当前{len(cl) if isinstance(cl, list) else 0}条，需>=3）"
            )
        kt = industry.get("key_trends", [])
        if not isinstance(kt, list) or len(kt) < 3:
            errors.append(
                f"l0.industry.key_trends 不足（当前{len(kt) if isinstance(kt, list) else 0}条，需>=3）"
            )

    # 客户字段
    clients = data.get("clients", [])
    if not isinstance(clients, list) or len(clients) == 0:
        errors.append("clients 为空或不是数组")
    else:
        for i, c in enumerate(clients):
            for field in REQUIRED_FIELDS["client"]:
                if field not in c:
                    errors.append(f"clients[{i}].{field} 缺失")
            # 检查 HTML 字段是否为空字符串
            html_fields = [
                "tags",
                "kpi_row",
                "basic_table",
                "equity_section",
                "veto_check",
                "decision_insight",
                "signal_insight",
            ]
            for hf in html_fields:
                if c.get(hf, "").strip() == "":
                    errors.append(f"clients[{i}].{hf} 为空（信息密度不足）")
            # V5: equity_section 必填 → 内容长度检查
            eq = c.get("equity_section", "")
            if len(eq.strip()) < 100:
                errors.append(
                    f"clients[{i}].equity_section 内容不足（需>=100字符，当前{len(eq.strip())}）"
                )
            # 检查结构化子字段
            for sf in REQUIRED_FIELDS.get("client_sub", []):
                if sf not in c:
                    errors.append(f"clients[{i}].{sf} 缺失")
            # 检查 procurement
            proc = c.get("procurement", {})
            for pf in ["scale_label", "estimate_range", "confidence", "method"]:
                if not proc.get(pf, "").strip():
                    errors.append(f"clients[{i}].procurement.{pf} 为空")
            if not proc.get("drivers") or len(proc.get("drivers", [])) < 2:
                errors.append(f"clients[{i}].procurement.drivers 不足（需>=2）")
            if not proc.get("evidence_items") or len(proc.get("evidence_items", [])) < 3:
                errors.append(f"clients[{i}].procurement.evidence_items 不足（需>=3）")
            # V5: 推算公式检查
            bc = proc.get("base_calc", {})
            if not bc.get("formula", "").strip():
                errors.append(f"clients[{i}].procurement.base_calc.formula 为空（推算公式必填）")
            if not bc.get("base_source", "").strip():
                errors.append(
                    f"clients[{i}].procurement.base_calc.base_source 为空（推算基数来源必填）"
                )
            # 检查 contact_cards
            if not isinstance(c.get("contact_cards"), list) or len(c.get("contact_cards", [])) < 2:
                errors.append(f"clients[{i}].contact_cards 不足（需>=2张）")
            # V5.2: 脉脉来源检查 — 必须有公开职业社交平台来源或降级标注
            cards = c.get("contact_cards", [])
            maimai_found = any(
                isinstance(card, dict)
                and (
                    card.get("source", "").startswith("公开职业社交平台")
                    or card.get("source", "").startswith("脉脉")
                )
                for card in cards
            )
            all_infer_only = all(
                isinstance(card, dict)
                and card.get("source", "") in ["工商登记", "行业推断", "企业官网"]
                for card in cards
            )
            no_maimai_notice = any(
                isinstance(card, dict)
                and (
                    "未能识别" in card.get("source", "")
                    or "无法获取" in card.get("source", "")
                    or "降级" in card.get("source", "")
                )
                for card in cards
            )
            # 硬约束：如果全部卡片都是工商/行业推断/官网来源，且无降级说明 → 报错
            if all_infer_only and not no_maimai_notice:
                errors.append(
                    f"clients[{i}].contact_cards 全部为工商登记/行业推断来源，"
                    f"缺少公开职业社交平台数据。请先采集 maimai-prospect "
                    f"或在 source 中标注降级原因（如'公开社交平台未能识别到决策人'）"
                )
            elif not maimai_found and not no_maimai_notice:
                errors.append(
                    f"clients[{i}].contact_cards 中无公开职业社交平台来源"
                    f"（需采集 maimai-prospect 或标注无法获取原因）"
                )
            # 检查 signals
            if not isinstance(c.get("signals"), list) or len(c.get("signals", [])) < 4:
                errors.append(f"clients[{i}].signals 不足（需>=4条）")
            # 检查 engagement
            eng = c.get("engagement", {})
            # V5: 向后兼容 — 优先检查 positioning（新），其次 elevator_pitch（旧）
            if not eng.get("positioning", "").strip() and not eng.get("elevator_pitch", "").strip():
                errors.append(f"clients[{i}].engagement.positioning 为空（定位话术必填）")
            if not eng.get("value_props") or len(eng.get("value_props", [])) < 3:
                errors.append(f"clients[{i}].engagement.value_props 不足（需>=3）")
            if not eng.get("entry_points") or len(eng.get("entry_points", [])) < 3:
                errors.append(f"clients[{i}].engagement.entry_points 不足（需>=3）")
            if not eng.get("timeline_steps") or len(eng.get("timeline_steps", [])) < 3:
                errors.append(f"clients[{i}].engagement.timeline_steps 不足（需>=3）")
            # V5: 异议预判检查
            if not eng.get("objection_handlers") or len(eng.get("objection_handlers", [])) < 2:
                errors.append(f"clients[{i}].engagement.objection_handlers 不足（需>=2条异议预判）")
            # 检查 competition
            comp = c.get("competition", {})
            if not comp.get("competitors") or len(comp.get("competitors", [])) < 3:
                errors.append(f"clients[{i}].competition.competitors 不足（需>=3，V5 升级）")
            # V5: 向后兼容 — entry_barrier 可能是 dict（新）也可能是 str（旧）
            eb = comp.get("entry_barrier", {})
            if isinstance(eb, dict):
                for bf in ["technical", "certification", "relationship", "price"]:
                    if not eb.get(bf, "").strip():
                        errors.append(f"clients[{i}].competition.entry_barrier.{bf} 为空")
            elif isinstance(eb, str) and not eb.strip():
                errors.append(f"clients[{i}].competition.entry_barrier 为空")
            if not comp.get("our_differentiation") or len(comp.get("our_differentiation", [])) < 3:
                errors.append(
                    f"clients[{i}].competition.our_differentiation 不足（需>=3，V5 升级）"
                )
            # V5: 切换成本检查 — V5.4 支持新旧两种结构
            sc = comp.get("switching_cost", {})
            if isinstance(sc, dict):
                for scf in ["financial", "time", "risk"]:
                    sc_val = sc.get(scf)
                    if isinstance(sc_val, dict):
                        # V5.4: 结构化 {value, label, sub_items}
                        if not sc_val.get("value", "").strip():
                            errors.append(
                                f"clients[{i}].competition.switching_cost.{scf}.value 为空"
                            )
                        sub_items = sc_val.get("sub_items", [])
                        if isinstance(sub_items, list) and len(sub_items) < 2:
                            errors.append(
                                f"clients[{i}].competition.switching_cost.{scf}.sub_items 不足(需>=2)"
                            )
                    elif not str(sc_val).strip():
                        errors.append(f"clients[{i}].competition.switching_cost.{scf} 为空")
            # V5.4: substitution_path 结构检查
            sp = comp.get("substitution_path", {})
            if isinstance(sp, dict):
                if sp.get("steps"):
                    steps = sp["steps"]
                    if not isinstance(steps, list) or len(steps) < 3:
                        errors.append(
                            f"clients[{i}].competition.substitution_path.steps 不足(需>=3)"
                        )
                    else:
                        for k, step in enumerate(steps):
                            if isinstance(step, dict):
                                for fld in ["phase", "action", "duration", "barrier", "owner"]:
                                    if not step.get(fld, "").strip():
                                        errors.append(
                                            f"clients[{i}].competition.substitution_path.steps[{k}].{fld} 为空"
                                        )
                    if not sp.get("summary", "").strip():
                        errors.append(f"clients[{i}].competition.substitution_path.summary 为空")
                    if not sp.get("total_timeline", "").strip():
                        errors.append(
                            f"clients[{i}].competition.substitution_path.total_timeline 为空"
                        )
            # V5: 当前供应商推断检查
            if not comp.get("current_supplier_inference", "").strip():
                errors.append(f"clients[{i}].competition.current_supplier_inference 为空")
            # 检查 risks
            if not isinstance(c.get("risks"), list) or len(c.get("risks", [])) < 4:
                errors.append(f"clients[{i}].risks 不足（需>=4个）")
            # 检查 match_subscore_N
            for j in range(1, 9):
                sk = f"match_subscore_{j}"
                if sk not in c or not isinstance(c[sk], dict) or not c[sk].get("score"):
                    errors.append(f"clients[{i}].{sk} 缺失或不完整")
                # V5: 评分可追溯检查
                ms = c.get(sk, {})
                if isinstance(ms, dict):
                    if not ms.get("sub_scores"):
                        errors.append(f"clients[{i}].{sk}.sub_scores 为空（需记录子维度原始分）")
                    if not ms.get("raw_data", "").strip():
                        errors.append(
                            f"clients[{i}].{sk}.raw_data 为空（需记录评分依据的原始数据）"
                        )
                    if not ms.get("source", "").strip():
                        errors.append(f"clients[{i}].{sk}.source 为空（需标注数据来源）")

            # V5.3: 维度名称一致性检查
            for j in range(1, 9):
                sk = f"match_subscore_{j}"
                ms = c.get(sk, {})
                if isinstance(ms, dict):
                    actual_label = ms.get("label", "")
                    expected_label = STANDARD_LABELS[j - 1]
                    if actual_label and actual_label != expected_label:
                        errors.append(
                            f"clients[{i}].{sk}.label = {actual_label!r}, expected {expected_label!r}"
                        )
    # 附录字段
    appendix = data.get("appendix", {})
    for field in REQUIRED_FIELDS["appendix"]:
        if field not in appendix:
            errors.append(f"appendix 缺少字段: {field}")

    return errors


def check_output(html):
    # 检查渲染输出质量，返回 (errors, warnings) 元组
    warnings = []
    errors = []

    # V5.4: CSS 泄露检测 — </style> 之后不应有裸 CSS 选择器
    # 在 </style> 之后、<body 之前出现 .class 或 #id 选择器即为 CSS 泄露
    css_leak = re.search(r"</style>\s*\n\s*[.#@]", html)
    if css_leak:
        context = html[css_leak.start() : css_leak.start() + 120]
        errors.append(f"CSS 泄露: </style> 后发现裸 CSS 规则，位置: ...{context[:80]}...")

    # 残留未渲染变量
    residue = re.findall(r"\{\{[^}]*\}\}", html)
    if residue:
        warnings.append(f"残留未渲染变量: {residue}")

    # 工具名泄漏
    for pattern, replacement in TOOL_LEAK_PATTERNS:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            warnings.append(
                f"工具名泄漏: 发现 {len(matches)} 处 '{pattern}' → 应替换为 '{replacement}'"
            )

    # 客户 section 数量
    client_sections = html.count('<section class="chapter">')
    expected = html.count("<h1>报告导读</h1>")  # L0 section 不算
    if client_sections < 1:
        warnings.append("客户 section 数量少于 1")

    # 检查每 section 的内容量（至少 3 个 h2 标题）
    h2_count = html.count("<h2>")
    if h2_count < 10:
        warnings.append(f"h2 标题数({h2_count})过少，信息密度不足")

    return errors, warnings


def check_content_density(data):
    # 检查报告内容密度，返回密度不足的警告
    warnings = []
    for i, c in enumerate(data.get("clients", [])):
        name = c.get("display_name", f"#{i + 1}")
        # 每个信号必须有日期
        for s in c.get("signals", []):
            if not s.get("date", "").strip():
                warnings.append(f"{name}: 信号「{s.get('category', '')}」缺少日期")
        # V5.3: signal quantification check
        for s in c.get("signals", []):
            detail = s.get("detail", "")
            if not re.search(r"\d+", str(detail)):
                warnings.append(
                    f"{name}: signal [{s.get('category', '')}] detail has no numeric data"
                )
        # engagement 语义检查
        eng = c.get("engagement", {})
        pitch = eng.get("positioning", "") or eng.get("elevator_pitch", "")
        if pitch and len(pitch) < 30:
            warnings.append(f"{name}: 定位话术过短（<30字）")
        # V5.3: entry point style check (no personal perspective)
        for ep in eng.get("entry_points", []):
            hook = ep.get("hook", "") if isinstance(ep, dict) else str(ep)
            if re.search(r"(total|manager|director|said|透露|曾说过)", str(hook)):
                warnings.append(f"{name}: entry point may use personal perspective")
        # risks level 分布检查
        levels = [r.get("level", "") for r in c.get("risks", [])]
        if "risk-high" not in levels:
            warnings.append(f"{name}: 缺少高风险项")

    # V5: L0 行业全景密度检查
    l0 = data.get("l0", {})
    industry = l0.get("industry", {})
    if industry:
        ms_val = (
            industry.get("market_size", {}).get("value", "")
            if isinstance(industry.get("market_size"), dict)
            else ""
        )
        if not re.search(r"20\d{2}", str(ms_val)):
            warnings.append("行业全景·市场规模：缺少当前年份数据")
        cm = industry.get("customer_map", [])
        if isinstance(cm, list) and len(cm) < 3:
            warnings.append(f"行业全景·目标客户地图：仅 {len(cm)} 个子行业（需>=3）")
        cl = industry.get("competitive_landscape", [])
        if isinstance(cl, list) and len(cl) < 3:
            warnings.append(f"行业全景·竞品格局：仅 {len(cl)} 家竞品（需>=3）")

    # V5.3: internal marker leak check — this runs in check_output() where html is defined
    return warnings


def check_l0_density(data):
    # V5 新增：L0 行业全景专项密度检查
    errors = []
    l0 = data.get("l0", {})
    industry = l0.get("industry", {})

    if not industry:
        # 向后兼容：如果仍是旧版 industry_overview HTML 块，用内容长度判断
        ov = l0.get("industry_overview", "").strip()
        if len(ov) < 300:
            errors.append(
                "l0.industry_overview 内容不足（需>=300字符，当前{len(ov)}）— 请使用 V5 版 industry 结构体"
            )
        return errors

    # 市场规模：含数字 + 年份 + V5.4 结构体检测
    ms = industry.get("market_size", {})
    if isinstance(ms, dict):
        # V5.4: 新结构体 {amount, ...} 优先检查
        has_new = ms.get("amount") and str(ms.get("amount", "")).strip()
        has_old = "value" in ms and str(ms.get("value", "")).strip()
        if has_new:
            # New format — skip value check
            if not ms.get("yoy_growth", "").strip():
                errors.append("l0.industry.market_size.yoy_growth 为空")
            sub_segs = ms.get("sub_segments", [])
            if not isinstance(sub_segs, list) or len(sub_segs) < 3:
                errors.append(
                    f"l0.industry.market_size.sub_segments 不足(需>=3，当前{len(sub_segs) if isinstance(sub_segs, list) else 0})"
                )
        elif has_old:
            # Old format check
            ms_val = str(ms.get("value", ""))
            if ms_val.count("。") >= 2:
                errors.append(
                    f"l0.industry.market_size.value 为段落文本({len(ms_val)}字)，请升级为V5.4结构体"
                )
            elif not re.search(r"20\d{2}", ms_val):
                errors.append(f"l0.industry.market_size.value 缺少年份引用: {ms_val[:80]}")
        else:
            errors.append("l0.industry.market_size 缺少 amount 或 value 字段")
    else:
        errors.append("l0.industry.market_size 必须为结构体")

    # 产业链卡位 — V5.4 多层结构体检测
    ep = industry.get("eitia_position", {})
    if isinstance(ep, dict):
        # V5.4: 优先检查新版多层结构
        if ep.get("my_tier"):
            for key in ["my_tier", "my_subcategory"]:
                if not ep.get(key, "").strip():
                    errors.append(f"l0.industry.eitia_position.{key} 为空")
            ul = ep.get("upstream_layers")
            if not isinstance(ul, list) or len(ul) < 1:
                errors.append(
                    f"l0.industry.eitia_position.upstream_layers 不足(需>=1，当前{len(ul) if isinstance(ul, list) else 0})"
                )
            else:
                for j, layer in enumerate(ul):
                    for f in ["tier", "category", "products"]:
                        if isinstance(layer, dict) and not layer.get(f, "").strip():
                            errors.append(
                                f"l0.industry.eitia_position.upstream_layers[{j}].{f} 为空"
                            )
            dd = ep.get("downstream_direct")
            if not isinstance(dd, list) or len(dd) < 1:
                errors.append(
                    f"l0.industry.eitia_position.downstream_direct 不足(需>=1，当前{len(dd) if isinstance(dd, list) else 0})"
                )
            else:
                for j, layer in enumerate(dd):
                    for f in ["tier", "category", "products"]:
                        if isinstance(layer, dict) and not layer.get(f, "").strip():
                            errors.append(
                                f"l0.industry.eitia_position.downstream_direct[{j}].{f} 为空"
                            )
        elif not ep.get("tier", "").strip():
            errors.append("l0.industry.eitia_position.tier 为空")

    # 目标客户地图
    cm = industry.get("customer_map", [])
    if isinstance(cm, list):
        if len(cm) < 3:
            errors.append(f"l0.industry.customer_map 仅 {len(cm)} 条（需>=3）")
        for j, item in enumerate(cm):
            if isinstance(item, dict) and not item.get("description", "").strip():
                errors.append(f"l0.industry.customer_map[{j}].description 为空")
    else:
        errors.append("l0.industry.customer_map 不是数组")

    # 竞品格局
    cl = industry.get("competitive_landscape", [])
    if isinstance(cl, list):
        if len(cl) < 3:
            errors.append(f"l0.industry.competitive_landscape 仅 {len(cl)} 家（需>=3）")
    else:
        errors.append("l0.industry.competitive_landscape 不是数组")

    # 关键趋势
    kt = industry.get("key_trends", [])
    if isinstance(kt, list):
        if len(kt) < 3:
            errors.append(f"l0.industry.key_trends 仅 {len(kt)} 条（需>=3）")
        for j, item in enumerate(kt):
            if isinstance(item, dict):
                if not item.get("trend", "").strip():
                    errors.append(f"l0.industry.key_trends[{j}].trend 为空")
                if not item.get("driver", "").strip():
                    errors.append(f"l0.industry.key_trends[{j}].driver 为空")
    else:
        errors.append("l0.industry.key_trends 不是数组")

    return errors


def check_gov_role(data):
    """V5.4: 关键决策人 gov_role 硬门禁 — 工商来源卡片必须有 gov_role"""
    errors = []
    warnings = []
    for i, c in enumerate(data.get("clients", [])):
        name = c.get("display_name", f"#{i + 1}")
        for j, card in enumerate(c.get("contact_cards", [])):
            source = card.get("source", "")
            gov_role = card.get("gov_role", "")
            # 工商来源 = 必须携带董监高角色
            if re.search(r"工商|gongshang|登记", source, re.IGNORECASE):
                if not gov_role or not gov_role.strip():
                    errors.append(
                        f"{name}.contact_cards[{j}] (source={source}) 缺少 gov_role 字段 "
                        f'— 工商登记来源的决策人必须标注董监高角色(如"董事""总经理")'
                    )
            # 脉脉来源携带 gov_role = 交叉验证正常，但提醒确认
            if re.search(r"脉脉|maimai|职业社交", source, re.IGNORECASE):
                if gov_role and gov_role.strip():
                    warnings.append(
                        f"{name}.contact_cards[{j}] (source={source}) 含 gov_role={gov_role}，"
                        f"请确认该角色来自工商数据交叉验证而非脉脉推断"
                    )
    return errors, warnings


def check_appendix_density(data):
    """V5.4: 附录内容密度检查"""
    errors = []
    app = data.get("appendix", {})

    # 附录 A: data_log 必须含 <tr>（表格行），≥ 10 行
    dl = app.get("data_log", "")
    if isinstance(dl, str):
        tr_count = len(re.findall(r"<tr[>\s]", dl))
        if tr_count < 10:
            errors.append(f"附录A data_log: 表格行数不足(需>=10行，当前{tr_count}行)")

    # 附录 B: scoring_method 必须含子章节标记
    sm = app.get("scoring_method", "")
    if isinstance(sm, str):
        for marker in ["B.1", "B.2", "B.3"]:
            if marker not in sm:
                errors.append(f"附录B scoring_method: 缺少子章节标记 {marker}")
        if len(sm) < 300:
            errors.append(f"附录B scoring_method: 内容过短(需>=300字符，当前{len(sm)}字符)")

    # 附录 C: glossary 必须含 <dt> 标签，≥ 5 个
    gl = app.get("glossary", "")
    if isinstance(gl, str):
        dt_count = len(re.findall(r"<dt[>\s]", gl))
        if dt_count < 5:
            errors.append(f"附录C glossary: 术语数不足(需>=5个，当前{dt_count}个)")

    # 附录 D: disclaimer 必须含 ≥ 3 段
    disc = app.get("disclaimer", "")
    if isinstance(disc, str):
        p_count = len(re.findall(r"<p[>\s]", disc))
        if p_count < 3:
            errors.append(f"附录D disclaimer: 段落数不足(需>=3段，当前{p_count}段)")
        if len(disc) < 150:
            errors.append(f"附录D disclaimer: 内容过短(需>=150字符，当前{len(disc)}字符)")

    return errors


def render(data):
    # Jinja2 渲染
    from jinja2 import StrictUndefined

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,  # HTML 内容块使用 | safe 过滤器
        undefined=StrictUndefined,  # 缺失变量直接报错
    )

    try:
        template = env.get_template("eitia-cfr.html")
        return template.render(**data)
    except Exception as e:
        print(f"ERROR: Jinja2 渲染失败: {e}")
        raise


def check_listing_status(data):
    """V5.3: detect listing status contradictions"""
    warnings = []
    for i, c in enumerate(data.get("clients", [])):
        name = c.get("display_name", f"#{i + 1}")
        basic = c.get("basic_table", "")
        oneliner = c.get("oneliner", "")
        tags = str(c.get("tags", ""))
        combined = basic + oneliner + tags
        has_unlisted = "非上市" in combined
        has_stock_code = bool(re.search(r"\d{6}\.[A-Z]{2,3}", combined))
        if has_unlisted and has_stock_code:
            warnings.append(f"{name}: unlisted label but stock code found in basic_table/tags")
    return warnings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    data_path = Path(sys.argv[1])
    output_path = None
    check_only = False

    for arg in sys.argv[2:]:
        if arg == "--check-only":
            check_only = True
        elif arg.startswith("--output="):
            output_path = Path(arg.split("=", 1)[1])

    # 读取 JSON
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    # Step 1: 验证 JSON
    errors = validate_json(data)
    if errors:
        print(f"JSON 验证错误 ({len(errors)} 项):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"JSON 验证通过：{len(data.get('clients', []))} 家客户")

    # Step 1.5: L0 行业全景密度（V5 新增）
    l0_errors = check_l0_density(data)
    if l0_errors:
        print(f"L0 行业全景密度错误 ({len(l0_errors)} 项):")
        for e in l0_errors:
            print(f"  - {e}")
        sys.exit(1)
    print("L0 行业全景密度检查通过")

    # Step 1.6: V5.4 gov_role 硬门禁
    gov_errors, gov_warnings = check_gov_role(data)
    if gov_errors:
        print(f"gov_role 验证错误 ({len(gov_errors)} 项):")
        for e in gov_errors:
            print(f"  - {e}")
        sys.exit(1)
    if gov_warnings:
        print(f"gov_role 交叉验证提醒 ({len(gov_warnings)} 项):")
        for w in gov_warnings:
            print(f"  - {w}")
    print("gov_role 检查通过")

    # Step 1.7: V5.4 附录密度检查
    appendix_errors = check_appendix_density(data)
    if appendix_errors:
        print(f"附录密度错误 ({len(appendix_errors)} 项):")
        for e in appendix_errors:
            print(f"  - {e}")
        sys.exit(1)
    print("附录密度检查通过")

    # V5.3: listing status check
    listing_warnings = check_listing_status(data)
    if listing_warnings:
        print(f"listing status warnings ({len(listing_warnings)}):")
        for w in listing_warnings:
            print(f"  - {w}")
    print("listing status check passed")

    if check_only:
        return

    # Step 1.6: 内容密度检查
    density_warnings = check_content_density(data)
    if density_warnings:
        print(f"内容密度警告 ({len(density_warnings)} 项):")
        for w in density_warnings:
            print(f"  - {w}")

    # Step 2: 渲染
    try:
        html = render(data)
    except Exception:
        print("渲染失败，请检查 JSON 数据是否完整")
        sys.exit(1)

    # Step 3: 输出检查
    output_errors, warnings = check_output(html)
    if output_errors:
        print(f"输出质量错误 ({len(output_errors)} 项):")
        for e in output_errors:
            print(f"  - {e}")
        print("FATAL: 渲染输出存在质量问题，终止")
        sys.exit(1)
    if warnings:
        print(f"输出警告 ({len(warnings)} 项):")
        for w in warnings:
            print(f"  - {w}")
        if any("残留" in w for w in warnings):
            print("FATAL: 残留未渲染变量，终止")
            sys.exit(1)

    print("输出检查通过：无残留变量，无工具名泄漏，无CSS泄露")

    # Step 4: 保存
    if output_path is None:
        os.makedirs(REPORT_DIR, exist_ok=True)
        product = data["cover"]["product"].replace(" ", "_").replace("/", "-")[:30]
        ver = data["appendix"]["version"]
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = REPORT_DIR / f"EITIA_{product}_{date_str}_{ver}.html"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"报告已生成: {output_path} ({len(html)} bytes)")
    print(f"客户数: {len(data.get('clients', []))}, h2标题数: {html.count('<h2>')}")


if __name__ == "__main__":
    main()
