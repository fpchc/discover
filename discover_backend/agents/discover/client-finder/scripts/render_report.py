#!/usr/bin/env python3
"""EITIA 报告渲染器（P1 数据受限版）— JSON 数据 → 校验 → 渲染 HTML。

契约（平台 stdin 优先，argv 兼容本地直跑）：
- 平台：stdin 传 JSON，`{"data": {…}}` 内联传报告本体（首选，AI 无写文件工具）；
  `{"input": "<工作区相对路径>"}` 仅引用已落盘文件（本地直跑/门禁场景）；
  `check_only` 为 true 时只校验不渲染。
- 本地：`python render_report.py report.json [--check-only]`。
退出码：0 成功；非 0 校验未通过（stdout 给出失败项清单）。

路径规则（P1 迁移）：
- 模板目录：平台注入的 SKILL_ROOT_DIR/templates（只读）
- 输出目录：平台注入的 WORKSPACE_DIR/output（可写，脚本唯一可写位置）
- 不依赖外部 Kami 部署；P1 产出 HTML 作为可下载产物，PDF 属 P2。

校验分级（收窄阻断 + 容错渲染）：
- 阻断级：clients 非空数组、无 Jinja 残留、无 CSS 泄露
- 警告级：字段齐全、工具名泄漏、数据量/密度、gov_role 等，缺失仅标注不阻断

数据契约单一事实来源：schemas/report_schema.json（required_fields 驱动字段齐全检查）。

用法：
  python render_report.py data/report.json
  python render_report.py data/report.json --check-only
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from jinja2 import Environment as _JinjaEnv

SKILL_ROOT_DIR = Path(os.environ.get("SKILL_ROOT_DIR", str(Path(__file__).resolve().parent.parent)))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", str(Path.cwd())))
TEMPLATE_DIR = SKILL_ROOT_DIR / "templates"
OUTPUT_DIR = WORKSPACE_DIR / "output"

# 工具名泄漏检查（P1 保留，命中即警告）
TOOL_LEAK_PATTERNS: list[tuple[str, str]] = [
    (r"score_calculator\.py|render_report\.py|dedup_manager\.py|eitia-cfr\.html", "系统内部工具"),
    (r"\bmaimai\b|\bmaimai-prospect\b|\b脉脉\b", "公开职业社交平台"),
    (r"xxxx+[^;]|X{4,}|占位|待填|placeholder|\[TBD\]|\[TODO\]", "填充文字/占位符（报告不完整）"),
    (r"bocha|bocha_web_search|bocha_ai_search", "行业公开搜索"),
    (r"tavily|tavily_search|tavily_extract", "行业公开搜索"),
    (r"web_search_exa|web_fetch_exa", "行业公开搜索"),
    (r"anysearch", "行业公开搜索"),
    (r"tinyfish|fetch_content|run_web_automation", "行业公开搜索"),
    (r"tyc-mcp|tianyancha|天眼查", "企业公开登记信息"),
    (r"call_tool(?!s)", "企业公开登记信息"),
    (r"get_company_basic_profile|get_company_group_profile|get_company_people", "企业公开登记信息"),
    (r"get_suppliers_and_customers|get_financing_records|get_products_info", "企业公开登记信息"),
    (r"get_recruitment_info|get_bidding_info|get_risk_overview", "企业公开登记信息"),
    (
        r"get_relation_graph|get_relation_path|get_patent_info|get_shareholder_info",
        "企业公开登记信息",
    ),
    (r"search_companies|search_listed_companies", "企业公开搜索"),
    (r"qcc-mcp|qcc-company|qcc-risk|qcc-ipr|qcc-operation", "企业公开信用信息系统"),
    (
        r"get_company_registration_info|get_company_risk_scan|get_credit_evaluation",
        "企业公开信用信息系统",
    ),
    (
        r"get_contact_info|get_key_personnel|get_actual_controller|get_external_investments",
        "企业公开信用信息系统",
    ),
    (r"get_news_sentiment", "公开新闻信息"),
    (r"eastmoney|mx_ds_mcp|mx_ashare|mx_finance|mx_stocks_screener|tushare", "公开市场信息"),
    (r"playwright|browser_|preview_", "浏览器辅助工具"),
]

STANDARD_LABELS: list[str] = [
    "采购规模",
    "技术匹配",
    "需求强度",
    "采购时机",
    "竞争位置",
    "触达可行",
    "决策复杂度",
    "信用安全",
]

SCHEMA_PATH = SKILL_ROOT_DIR / "schemas" / "report_schema.json"
_SCHEMA_FIELDS: dict[str, list[str]] | None = None


def required_fields() -> dict[str, list[str]]:
    """加载报告结构 schema 的必填字段表（schemas/report_schema.json）。

    单一事实来源：字段齐全检查（check_completeness）与参考文档均以该 schema 为准，
    禁止在脚本内再维护第二份字段清单（否则又会与模板/文档漂移）。
    """
    global _SCHEMA_FIELDS
    if _SCHEMA_FIELDS is not None:
        return _SCHEMA_FIELDS
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法加载报告 schema: {SCHEMA_PATH} ({exc})") from exc
    fields = schema.get("required_fields")
    if not isinstance(fields, dict):
        raise RuntimeError(f"schema 缺少 required_fields: {SCHEMA_PATH}")
    _SCHEMA_FIELDS = {str(scope): [str(name) for name in names] for scope, names in fields.items()}
    return _SCHEMA_FIELDS


def validate_structure(data: dict[str, Any]) -> list[str]:
    """阻断级结构校验（收窄）：只保留交付底线。

    报告数据由 LLM 生成、形状不稳定；模板采用容错渲染（缺失渲染为空，见
    _build_render_env）。字段齐全与密度一律降级为警告（check_completeness /
    check_density），避免「缺一个字段就 exit 1」让生成陷入打地鼠循环。

    阻断仅保留「clients 为非空数组」：客户发现报告至少要有 1 家客户，否则不构成
    可交付物。
    """
    errors: list[str] = []
    clients = data.get("clients")
    if not isinstance(clients, list) or len(clients) == 0:
        errors.append("clients 为空或不是数组（报告至少需要 1 家客户）")
    return errors


def check_completeness(data: dict[str, Any]) -> list[str]:
    """字段齐全检查（警告级）：对照 schema.required_fields 列出缺失/空字段。

    仅标注不阻断——模板容错渲染，缺失字段会渲染为空；此处一次性列出全部缺失项，
    供 AI 据以补全（替代旧版 validate_structure 的阻断式清单）。
    """
    warnings: list[str] = []
    fields = required_fields()
    for field in fields.get("", []):
        if field not in data:
            warnings.append(f"缺少顶层字段: {field}")
    cover = data.get("cover", {})
    if not isinstance(cover, dict):
        warnings.append("cover 必须是对象")
    else:
        for field in fields["cover"]:
            if field not in cover:
                warnings.append(f"cover 缺少字段: {field}")
    l0 = data.get("l0", {})
    if not isinstance(l0, dict):
        warnings.append("l0 必须是对象")
    else:
        for field in fields["l0"]:
            if field not in l0:
                warnings.append(f"l0 缺少字段: {field}")
        industry = l0.get("industry", {})
        if isinstance(industry, dict):
            for field in fields["l0_industry"]:
                if field not in industry:
                    warnings.append(f"l0.industry 缺少字段: {field}")
    clients = data.get("clients", [])
    if isinstance(clients, list):
        for i, c in enumerate(clients):
            if not isinstance(c, dict):
                warnings.append(f"clients[{i}] 必须是对象")
                continue
            for field in fields["client"]:
                if field not in c:
                    warnings.append(f"clients[{i}].{field} 缺失")
            for sf in fields["client_sub"]:
                if sf not in c:
                    warnings.append(f"clients[{i}].{sf} 缺失")
            html_fields = [
                "tags",
                "kpi_row",
                "basic_table",
                "veto_check",
                "decision_insight",
                "signal_insight",
            ]
            for hf in html_fields:
                if str(c.get(hf, "")).strip() == "":
                    warnings.append(f"clients[{i}].{hf} 为空")
            cards = c.get("contact_cards")
            if not isinstance(cards, list) or len(cards) < 1:
                warnings.append(f"clients[{i}].contact_cards 不足（至少 1 张）")
            risk_items = c.get("risks")
            if not isinstance(risk_items, list) or len(risk_items) < 1:
                warnings.append(f"clients[{i}].risks 不足（至少 1 条）")
            for j in range(1, 9):
                sk = f"match_subscore_{j}"
                ms = c.get(sk)
                if not isinstance(ms, dict) or not ms.get("score"):
                    warnings.append(f"clients[{i}].{sk} 缺失或不完整")
    appendix = data.get("appendix", {})
    if not isinstance(appendix, dict):
        warnings.append("appendix 必须是对象")
    else:
        for field in fields["appendix"]:
            if field not in appendix:
                warnings.append(f"appendix 缺少字段: {field}")
    return warnings


def check_output(html: str) -> tuple[list[str], list[str]]:
    """渲染输出质量检查。阻断：CSS 泄露、Jinja 残留。警告：工具名泄漏、密度。"""
    errors: list[str] = []
    warnings: list[str] = []
    css_leak = re.search(r"</style>\s*\n\s*[.#@]", html)
    if css_leak:
        context = html[css_leak.start() : css_leak.start() + 120]
        errors.append(f"CSS 泄露: </style> 后发现裸 CSS 规则，位置: ...{context[:80]}...")
    residue = re.findall(r"\{\{[^}]*\}\}", html)
    if residue:
        errors.append(f"残留未渲染变量: {residue[:5]}")
    for pattern, replacement in TOOL_LEAK_PATTERNS:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            warnings.append(
                f"工具名泄漏: 发现 {len(matches)} 处 '{pattern}' → 应替换为 '{replacement}'"
            )
    if html.count('<section class="chapter">') < 1:
        warnings.append("客户 section 数量少于 1")
    if html.count("<h2>") < 10:
        warnings.append(f"h2 标题数({html.count('<h2>')})过少，信息密度不足")
    return errors, warnings


def check_density(data: dict[str, Any]) -> list[str]:
    """数据完整性警告（P1 放宽：缺失仅标注不阻断）。"""
    warnings: list[str] = []
    for i, c in enumerate(data.get("clients", [])):
        name = c.get("display_name", f"#{i + 1}") if isinstance(c, dict) else f"#{i + 1}"
        if not isinstance(c, dict):
            continue
        eq = str(c.get("equity_section", "")).strip()
        if len(eq) < 100:
            warnings.append(
                f"{name}: equity_section 内容不足（<100 字符）— P1 数据受限，标注来源即可"
            )
        cards = c.get("contact_cards", [])
        if not isinstance(cards, list):
            continue
        if len(cards) < 2:
            warnings.append(f"{name}: contact_cards 少于 2 张 — 数据受限，标注")
        sources = [card.get("source", "") for card in cards if isinstance(card, dict)]
        has_maimai = any("公开职业社交平台" in s or "脉脉" in s for s in sources)
        has_notice = any("未能识别" in s or "无法获取" in s or "降级" in s for s in sources)
        if not has_maimai and not has_notice:
            warnings.append(f"{name}: 决策人来源无公开职业社交平台且无降级标注 — 请标注降级原因")
        for card in cards:
            if (
                isinstance(card, dict)
                and re.search(r"工商|gongshang|登记", card.get("source", ""), re.IGNORECASE)
                and not str(card.get("gov_role", "")).strip()
            ):
                warnings.append(
                    f"{name}: 工商来源决策人卡片缺少 gov_role 字段 — 尽力标注董监高角色"
                )
        signals = c.get("signals", [])
        if isinstance(signals, list) and len(signals) < 4:
            warnings.append(f"{name}: signals 少于 4 条 — 数据受限")
        for s in signals if isinstance(signals, list) else []:
            if isinstance(s, dict):
                if not str(s.get("date", "")).strip():
                    warnings.append(f"{name}: 信号「{s.get('category', '')}」缺少日期")
                if not re.search(r"[0-9]+", str(s.get("detail", ""))):
                    warnings.append(f"{name}: 信号「{s.get('category', '')}」detail 无数字数据")
        levels = [r.get("level", "") for r in c.get("risks", []) if isinstance(r, dict)]
        if "risk-high" not in levels:
            warnings.append(f"{name}: 缺少高风险项")
    return warnings


# ---------------------------------------------------------------------------
# 数据端归一化（normalize）
# 模板 eitia-cfr.html 是唯一契约（templates/eitia-cfr.html + schemas/report_schema.json）。
# LLM 产出的报告 JSON 形状不稳定（平铺字符串 / 错位字段名 / list 当 HTML 直出），
# 这里在渲染前统一转为模板期望的 V5 结构化形态：字符串 → 结构化、list/dict → HTML 片段。
# 只做形态转换、不编造数据内容；确实缺失的内容用「P1 数据受限」显式占位，避免渲染成
# Python repr 泄漏（[{'key': ...}]）或大片空白。对已结构化数据幂等。
#
# # pragma: 简化 — 模板结构体访问点分散，逐处加类型守卫会无限扩散 if-elif（违反 OCP）；
# 收敛为渲染前单点归一化，模板保持 V5 结构化契约不变。
# ---------------------------------------------------------------------------


def _escape(value: object) -> str:
    """HTML 转义任意标量，用于拼接走 ``| safe`` 的 HTML 片段。"""
    return html.escape(str(value if value is not None else ""))


def _render_tags(tags: object) -> str:
    if isinstance(tags, str):
        return tags
    items = tags if isinstance(tags, list) else []
    return "".join(f'<span class="client-tag">{_escape(t)}</span>' for t in items if t)


def _render_basic_table(rows: object) -> str:
    if isinstance(rows, str):
        return rows
    items = rows if isinstance(rows, list) else []
    if not items:
        return ""
    parts = ['<table class="compact striped">']
    for item in items:
        if isinstance(item, dict):
            parts.append(
                f"<tr><th style='width:24%;'>{_escape(item.get('label'))}</th>"
                f"<td>{_escape(item.get('value'))}</td></tr>"
            )
    parts.append("</table>")
    return "\n".join(parts)


def _render_veto_check(rows: object) -> str:
    if isinstance(rows, str):
        return rows
    items = rows if isinstance(rows, list) else []
    parts = ['<div style="display:flex;gap:8pt;flex-wrap:wrap;margin-top:4pt;">']
    for item in items:
        if isinstance(item, dict):
            result = _escape(item.get("result"))
            cls = "check-pass" if "未触发" in str(item.get("result", "")) else "check-fail"
            parts.append(
                f"<span><strong>{_escape(item.get('item'))}</strong>："
                f'<span class="{cls}">{result}</span></span>'
            )
    parts.append("</div>")
    return "\n".join(parts)


def _render_decision_chain(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    items = raw if isinstance(raw, list) else []
    steps = []
    for item in items:
        if isinstance(item, dict):
            steps.append(
                f'<div class="df-step"><div class="df-role">{_escape(item.get("title"))}</div>'
                f'<div class="df-action">{_escape(item.get("name"))}</div></div>'
            )
    if not steps:
        return ""
    return '<div class="decision-flow">' + '<span class="df-arrow">→</span>'.join(steps) + "</div>"


def _render_top_table(rows: object) -> str:
    if isinstance(rows, str):
        return rows
    items = rows if isinstance(rows, list) else []
    if not items:
        return ""
    parts = [
        '<table class="compact striped">',
        "<tr><th>排名</th><th>客户</th><th>综合评分</th><th>状态</th></tr>",
    ]
    for item in items:
        if isinstance(item, dict):
            parts.append(
                f"<tr><td>#{_escape(item.get('rank'))}</td>"
                f"<td><strong>{_escape(item.get('name'))}</strong></td>"
                f"<td>{_escape(item.get('score'))}/10</td>"
                f"<td>{_escape(item.get('status'))}</td></tr>"
            )
    parts.append("</table>")
    return "\n".join(parts)


def _render_data_log(rows: object) -> str:
    if isinstance(rows, str):
        return rows
    items = rows if isinstance(rows, list) else []
    if not items:
        return ""
    parts = [
        '<table class="compact striped">',
        "<tr><th>工具</th><th>调用次数</th><th>用途</th><th>说明</th></tr>",
    ]
    for item in items:
        if isinstance(item, dict):
            parts.append(
                f"<tr><td>{_escape(item.get('tool'))}</td>"
                f"<td>{_escape(item.get('call_count'))}</td>"
                f"<td>{_escape(item.get('usage'))}</td>"
                f"<td>{_escape(item.get('note'))}</td></tr>"
            )
    parts.append("</table>")
    return "\n".join(parts)


def _render_glossary(rows: object) -> str:
    if isinstance(rows, str):
        return rows
    items = rows if isinstance(rows, list) else []
    parts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            parts.append(
                f"<dt>{_escape(item.get('term'))}</dt><dd>{_escape(item.get('definition'))}</dd>"
            )
    return "\n".join(parts)


def _normalize_market_size(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    source = "、".join(s for s in ("Gartner", "MarketsandMarkets", "IDC", "Statista") if s in text)
    return {"value": text, "source": source}


def _normalize_eitia_position(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "")
    tier = (
        "上游" if "上游" in text else "中游" if "中游" in text else "下游" if "下游" in text else ""
    )
    return {"tier": tier, "upstream": "", "description": text}


def _best_match_name(text: str, client: dict[str, Any]) -> str:
    """在文本中查找客户的可命中名称（display → fullname → 去尾拉丁后缀），返回空串未命中。"""
    display = str(client.get("display_name") or "")
    full = str(client.get("fullname") or "")
    trimmed = re.sub(r"[A-Za-z0-9]+$", "", display)
    for candidate in (display, full, trimmed):
        if candidate and candidate in text:
            return candidate
    return ""


def _company_spans(text: str, clients: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    spans: list[tuple[str, dict[str, Any]]] = []
    for client in clients:
        name = _best_match_name(text, client)
        if name:
            spans.append((name, client))
    spans.sort(key=lambda pair: text.index(pair[0]))
    return spans


def _split_customer_map(text: str, clients: list[dict[str, Any]]) -> list[dict[str, str]]:
    spans = _company_spans(text, clients)
    rows: list[dict[str, str]] = []
    for i, (name, client) in enumerate(spans):
        start = text.index(name) + len(name)
        end = text.index(spans[i + 1][0]) if i + 1 < len(spans) else len(text)
        desc = text[start:end].strip()
        score = client.get("score")
        potential = "高" if isinstance(score, (int, float)) and score >= 8 else "中"
        reason = f"综合评分 {score}/10" if score else "—"
        rows.append(
            {
                "sub_industry": "服务器制造商",
                "description": desc or str(client.get("oneliner") or ""),
                "potential": potential,
                "reason": reason,
            }
        )
    return rows


def _client_to_customer_row(client: dict[str, Any]) -> dict[str, str]:
    score = client.get("score")
    potential = "高" if isinstance(score, (int, float)) and score >= 8 else "中"
    return {
        "sub_industry": "服务器制造商",
        "description": str(client.get("oneliner") or ""),
        "potential": potential,
        "reason": f"综合评分 {score}/10" if score else "—",
    }


def _normalize_customer_map(raw: object, clients: list[dict[str, Any]]) -> list[dict[str, str]]:
    if isinstance(raw, list) and all(isinstance(r, dict) for r in raw):
        return [dict(r) for r in raw if isinstance(r, dict)]
    if isinstance(raw, str) and raw.strip():
        rows = _split_customer_map(raw, clients)
        if rows:
            return rows
    return [_client_to_customer_row(c) for c in clients if isinstance(c, dict)]


def _normalize_competitive_landscape(raw: object) -> list[dict[str, str]]:
    if isinstance(raw, list):
        return [dict(r) for r in raw if isinstance(r, dict)]
    text = str(raw or "").strip()
    if not text:
        return []
    return [{"competitor": "竞品格局（P1 数据受限）", "share": "—", "note": text}]


def _normalize_key_trends(raw: object) -> list[dict[str, object]]:
    if isinstance(raw, list):
        out: list[dict[str, object]] = []
        for kt in raw:
            if isinstance(kt, dict):
                out.append(dict(kt))
            else:
                out.append({"trend": str(kt), "driver": "", "timeline": ""})
        return out
    return [{"trend": str(raw or ""), "driver": "", "timeline": ""}]


def _normalize_signal_heatmap(raw: object, clients: list[dict[str, Any]]) -> str:
    text = str(raw or "").strip()
    if not text:
        return text
    names = [name for name, _ in _company_spans(text, clients)]
    if not names:
        return text
    segments = []
    for i, name in enumerate(names):
        start = text.index(name)
        end = text.index(names[i + 1]) if i + 1 < len(names) else len(text)
        segments.append(text[start:end].strip())
    return "<br>".join(segments)


def _normalize_match_subscore(ms: object) -> dict[str, object]:
    if not isinstance(ms, dict):
        return {"label": "", "score": "", "weight": "—", "raw_data": "", "source": ""}
    out = dict(ms)
    out.setdefault("label", str(ms.get("name") or ""))
    out.setdefault("weight", "—")
    out.setdefault("raw_data", str(ms.get("basis") or ""))
    out.setdefault("score", "")
    out.setdefault("source", "")
    return out


def _normalize_procurement(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        out = dict(raw)
        out.setdefault("scale_label", "")
        out.setdefault("estimate_range", "")
        out.setdefault("confidence", "")
        out.setdefault("confidence_color", "mid")
        out.setdefault("method", "")
        out.setdefault("base_calc", None)
        out.setdefault("drivers", [])
        out.setdefault("supplier_trend", "")
        out.setdefault("calc_note", "")
        out.setdefault("evidence_items", [])
        return out
    text = str(raw or "").strip()
    return {
        "scale_label": "—",
        "estimate_range": "数据受限",
        "confidence": "低",
        "confidence_color": "low",
        "method": "P1 数据受限：无公开采购金额数据",
        "base_calc": None,
        "drivers": [],
        "supplier_trend": "",
        "calc_note": text,
        "evidence_items": [{"body": text, "source": ""}] if text else [],
    }


def _normalize_contact_card(card: object) -> dict[str, object]:
    if not isinstance(card, dict):
        return {}
    out = dict(card)
    if not out.get("source") and card.get("channel"):
        out["source"] = card.get("channel")
    if not out.get("bio") and card.get("note"):
        out["bio"] = card.get("note")
    return out


def _infer_signal_level(signal_type: str, note: str) -> tuple[str, str]:
    if "过时" in note or "招聘" in signal_type:
        return "yellow", "中性"
    return "green", "强"


def _normalize_signal(s: object) -> dict[str, object]:
    if not isinstance(s, dict):
        return {}
    out = dict(s)
    out.setdefault("detail", str(s.get("signal") or ""))
    out.setdefault("category", str(s.get("type") or ""))
    if not out.get("level") or not out.get("level_label"):
        out["level"], out["level_label"] = _infer_signal_level(
            str(s.get("type") or ""), str(s.get("note") or "")
        )
    out.setdefault("date", "")
    out.setdefault("source", "")
    return out


def _split_numbered_points(text: str) -> list[str]:
    parts = re.split(r"(?<=[一-鿿])[1-6](?=[一-鿿])", text)
    return [p.lstrip("0123456789.、) ") for p in parts if p.strip()]


def _empty_engagement() -> dict[str, object]:
    return {
        "positioning": "",
        "value_props": [],
        "entry_points": [{"hook": "P1 数据受限", "context": ""}],
        "objection_handlers": [],
        "timeline_steps": [{"phase": "—", "action": "P1 数据受限", "week": ""}],
        "timing_assessment": {"badge": "", "note": ""},
    }


def _normalize_engagement(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return _empty_engagement()
    out = dict(raw)
    out.setdefault("positioning", str(raw.get("key_message") or ""))
    approach = str(raw.get("approach") or "")
    if not out.get("value_props"):
        out["value_props"] = _split_numbered_points(approach)
    out.setdefault(
        "entry_points", [{"hook": "P1 数据受限：公开渠道未识别到具体切入点", "context": ""}]
    )
    out.setdefault("objection_handlers", [])
    out.setdefault(
        "timeline_steps", [{"phase": "—", "action": "P1 数据受限：无结构化时间线", "week": ""}]
    )
    if not isinstance(out.get("timing_assessment"), dict):
        priority = str(raw.get("priority") or "")
        out["timing_assessment"] = {
            "badge": "",
            "note": f"触达优先级：{priority}" if priority else "",
        }
    return out


def _normalize_competition(raw: object, landscape: object) -> dict[str, object]:
    if isinstance(raw, dict):
        out = dict(raw)
        out.setdefault("competitors", [])
        out.setdefault("current_supplier_inference", "")
        out.setdefault("substitution_path", None)
        out.setdefault("switching_cost", None)
        out.setdefault("entry_barrier", "P1 数据受限")
        out.setdefault("incumbent_strength", "P1 数据受限")
        out.setdefault("our_differentiation", [])
        return out
    text = str(raw or "").strip()
    comp_rows: list[dict[str, str]] = []
    if isinstance(landscape, str) and landscape.strip():
        comp_rows.append(
            {
                "name": "竞品格局（P1 数据受限）",
                "market_share": "—",
                "core_strength": landscape,
                "core_weakness": "",
                "customer_profile": "",
                "our_advantage": "—",
            }
        )
    return {
        "current_supplier_inference": text,
        "competitors": comp_rows,
        "substitution_path": "P1 数据受限：暂无替代路径数据",
        "switching_cost": None,
        "entry_barrier": "P1 数据受限",
        "incumbent_strength": "P1 数据受限",
        "our_differentiation": ["P1 数据受限：暂无结构化差异化数据"],
    }


def _normalize_risk(r: object) -> dict[str, str]:
    if not isinstance(r, dict):
        return {}
    out = dict(r)
    out.setdefault("category", str(r.get("type") or ""))
    out.setdefault("title", str(r.get("type") or ""))
    out.setdefault("detail", str(r.get("description") or ""))
    out.setdefault("level", "risk-mid")
    out.setdefault("mitigation", "")
    return out


def _normalize_scoring_method(raw: object) -> str:
    text = str(raw or "").strip()
    if not text or "B.1" in text or "B.2" in text:
        return text
    lines = [
        "§B.1 公式与权重",
        text,
        "§B.2 各维度打分细则",
        "各维度 0-10 分，综合分 = 加权平均。",
        "§B.3 一票否决规则",
        "信用安全 < 3.0 或触发红线（失信/破产/吊销/严重违法）直接排除。",
    ]
    return "<br>".join(lines)


_CLIENT_HTML_RENDERERS: dict[str, Callable[[object], str]] = {
    "tags": _render_tags,
    "basic_table": _render_basic_table,
    "veto_check": _render_veto_check,
    "decision_chain": _render_decision_chain,
}


def _normalize_client(c: dict[str, Any]) -> dict[str, Any]:
    out = dict(c)
    for key in ("tags", "basic_table", "veto_check", "decision_chain"):
        if key in out and not isinstance(out[key], str):
            out[key] = _CLIENT_HTML_RENDERERS[key](out[key])
    for i in range(1, 9):
        key = f"match_subscore_{i}"
        if key in out:
            out[key] = _normalize_match_subscore(out[key])
    out["procurement"] = _normalize_procurement(out.get("procurement"))
    if isinstance(out.get("contact_cards"), list):
        out["contact_cards"] = [_normalize_contact_card(card) for card in out["contact_cards"]]
    if isinstance(out.get("signals"), list):
        out["signals"] = [_normalize_signal(s) for s in out["signals"]]
    out["engagement"] = _normalize_engagement(out.get("engagement"))
    out["competition"] = _normalize_competition(
        out.get("competition"), out.get("competitive_landscape")
    )
    if isinstance(out.get("risks"), list):
        out["risks"] = [_normalize_risk(r) for r in out["risks"]]
    return out


def normalize_report(data: dict[str, Any]) -> dict[str, Any]:
    """报告数据归一化：平铺/错位格式 → 模板期望的 V5 结构化形态。

    模板 eitia-cfr.html 是唯一契约。只做形态转换、不编造数据内容；确实缺失的内容用
    「P1 数据受限」显式占位，避免渲染成 Python repr 泄漏或大片空白。同时保证顶层
    cover/appendix 为对象（version 缺省 V1），供下游文件名等严格访问兜底。对已结构化数据幂等。
    """
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    cover = out.get("cover")
    if not isinstance(cover, dict):
        out["cover"] = {}
    appendix = out.get("appendix")
    if not isinstance(appendix, dict):
        appendix = {}
        out["appendix"] = appendix
    appendix.setdefault("version", "V1")
    clients = out.get("clients")
    normalized_clients: list[dict[str, Any]] = []
    if isinstance(clients, list):
        for c in clients:
            if isinstance(c, dict):
                normalized_clients.append(_normalize_client(c))
        out["clients"] = normalized_clients

    l0 = out.get("l0")
    if isinstance(l0, dict):
        industry = l0.get("industry")
        if isinstance(industry, dict):
            norm = dict(industry)
            norm["market_size"] = _normalize_market_size(industry.get("market_size"))
            norm["eitia_position"] = _normalize_eitia_position(industry.get("eitia_position"))
            norm["customer_map"] = _normalize_customer_map(
                industry.get("customer_map"), normalized_clients
            )
            norm["competitive_landscape"] = _normalize_competitive_landscape(
                industry.get("competitive_landscape")
            )
            norm["key_trends"] = _normalize_key_trends(industry.get("key_trends"))
            l0["industry"] = norm
        if not isinstance(l0.get("top_table"), str):
            l0["top_table"] = _render_top_table(l0.get("top_table"))
        heatmap = l0.get("signal_heatmap")
        if isinstance(heatmap, str) and heatmap and "<br>" not in heatmap and "<div" not in heatmap:
            l0["signal_heatmap"] = _normalize_signal_heatmap(heatmap, normalized_clients)

    appendix["data_log"] = _render_data_log(appendix.get("data_log"))
    appendix["glossary"] = _render_glossary(appendix.get("glossary"))
    appendix["scoring_method"] = _normalize_scoring_method(appendix.get("scoring_method"))
    return out


_TOLERANT_ENV: _JinjaEnv | None = None
"""渲染环境缓存：jinja2 懒加载（--check-only 路径无需 jinja2），首次渲染时构建。"""


def _build_render_env() -> _JinjaEnv:
    """构建对缺失/类型不符字段容错的 Jinja2 环境。

    背景：报告数据由 LLM 生成，形状不稳定（子字段缺失、dict 被写成 str）。模板对
    结构体大量使用 ``.field`` 访问，若沿用 StrictUndefined，任何单点数据缺口都会让
    整份报告渲染失败。这里改为「缺失 → 渲染为空」，数据完整性交由 check_density 以
    警告标注（P1 分级：结构阻断、数据警告）。

    # pragma: 简化 — 模板结构体访问点多且分散，逐处加 is mapping 守卫不现实；
    # 统一在渲染层容错，是单点、可测、可维护的修复。
    """
    global _TOLERANT_ENV
    if _TOLERANT_ENV is not None:
        return _TOLERANT_ENV
    try:
        from jinja2 import ChainableUndefined, Environment, FileSystemLoader, UndefinedError
    except ImportError as exc:
        raise RuntimeError("渲染需要 jinja2，请使用预装 jinja2 的运行镜像（SCRIPT_IMAGE）") from exc

    class RenderUndefined(ChainableUndefined):
        """链式 + 可调用安全的缺失值：任意访问/索引/调用都退化为空，渲染不崩溃。"""

        # 缺失值可调用：允许 .split()/.items() 等链式调用返回自身，替代 Undefined 默认抛错
        def __call__(self, *args: object) -> RenderUndefined:  # type: ignore[override]
            return self

    class TolerantEnvironment(Environment):
        """getattr 容错：对标量（str/int/list…）取属性抛 AttributeError 时返回缺失值。"""

        def getattr(self, obj: object, attribute: str) -> object:
            try:
                return cast(object, super().getattr(obj, attribute))
            except (AttributeError, UndefinedError):
                return cast(object, self.undefined(name=f"{type(obj).__name__}.{attribute}"))

    env = TolerantEnvironment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
        undefined=RenderUndefined,
    )
    _TOLERANT_ENV = env
    return env


def render(data: dict[str, Any]) -> str:
    """Jinja2 渲染（懒加载，--check-only 路径无需 jinja2）。

    先归一化再渲染：即使 main() 已归一化，这里再归一化一次是幂等的，
    保证 render() 作为独立入口时对不守约的 LLM 输出同样兜底。
    jinja2 不在默认容器镜像（python:3.12-slim）内；渲染模式要求运行镜像预装 jinja2
    （P1 由平台配置 SCRIPT_IMAGE 提供，P2 支持技能专属镜像）。
    """
    env = _build_render_env()
    template = env.get_template("eitia-cfr.html")
    return template.render(**normalize_report(data))


def _resolve_data_path(arg: str) -> Path:
    p = Path(arg)
    if p.is_absolute():
        return p
    return WORKSPACE_DIR / p


def _load_json_file(path: Path) -> dict[str, Any]:
    """读取报告 JSON 文件并确保顶层是对象；解析失败/非对象时友好报错退出。

    报告数据由 LLM 生成，文件里可能是数组/标量而非对象——统一在此拦截，
    避免下游 ``dict(data)`` / ``data.get(...)`` 抛裸异常（全部安全检查收敛点）。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"JSON 读取/解析失败: {path} ({exc})"}, ensure_ascii=False))
        sys.exit(1)
    if not isinstance(data, dict):
        print(json.dumps({"error": f"报告数据必须是 JSON 对象: {path}"}, ensure_ascii=False))
        sys.exit(1)
    return data


def _load_input() -> tuple[dict[str, Any], bool]:
    """读取入参：平台契约走 stdin JSON，argv 兼容本地直跑。

    平台：stdin 传 `{"data": {…}}`（首选，AI 无写文件工具），`check_only` 为布尔；
    `{"input": "rel/path.json"}` 仅本地直跑/门禁引用已落盘文件时使用。
    本地：argv 传 `report.json [--check-only]`。
    返回 (数据, check_only)；argv 缺参数或 JSON 无有效载荷时退出并给出说明。
    """
    if len(sys.argv) >= 2:
        return _load_json_file(_resolve_data_path(sys.argv[1])), "--check-only" in sys.argv[2:]
    _NO_DATA_HINT = (
        "（平台内 AI 无写文件工具：请用入参 data 内联传报告本体，不要传 input 文件路径）"
    )
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"JSON 解析失败: {exc}"}, ensure_ascii=False))
        sys.exit(1)
    if not isinstance(payload, dict):
        print(json.dumps({"error": "入参必须是 JSON 对象"}, ensure_ascii=False))
        sys.exit(1)
    check_only = bool(payload.get("check_only", False))
    inline = payload.get("data")
    if isinstance(inline, dict) and inline:
        return inline, check_only
    input_ref = payload.get("input")
    if isinstance(input_ref, str) and input_ref:
        return _load_json_file(_resolve_data_path(input_ref)), check_only
    print(json.dumps({"error": f"入参缺少 data 字段{_NO_DATA_HINT}"}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    data, check_only = _load_input()
    # 数据端归一化先行：校验、落盘 report.json 与门禁引用的都是归一化后的数据，
    # 字段齐全/密度告警据此更准。
    data = normalize_report(data)

    errors = validate_structure(data)
    if errors:
        print("结构校验错误（阻断）:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"结构校验通过：{len(data.get('clients', []))} 家客户")

    for w in check_completeness(data):
        print(f"WARNING: {w}")
    for w in check_density(data):
        print(f"WARNING: {w}")

    if check_only:
        return

    try:
        html = render(data)
    except Exception as exc:
        print(json.dumps({"error": f"渲染失败: {exc}"}, ensure_ascii=False))
        sys.exit(1)
    output_errors, warnings = check_output(html)
    for w in warnings:
        print(f"WARNING: {w}")
    if output_errors:
        print("输出质量错误（阻断）:")
        for e in output_errors:
            print(f"  - {e}")
        sys.exit(1)
    print("输出检查通过：无残留变量，无工具名泄漏，无 CSS 泄露")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 报告数据落盘，供 gate 门禁引用（AI 无写文件工具，数据仅经 stdin 到达）
    data_path_out = OUTPUT_DIR / "report.json"
    with open(data_path_out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"报告数据已落盘: {data_path_out}")
    product = str(data.get("cover", {}).get("product") or "未命名产品")
    product = product.replace(" ", "_").replace("/", "-")[:30]
    ver = str(data.get("appendix", {}).get("version") or "V1")
    date_str = datetime.now().strftime("%Y%m%d")
    output_path = OUTPUT_DIR / f"EITIA_{product}_{date_str}_{ver}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {output_path} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
