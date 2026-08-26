"""render_report 数据端归一化（normalize_report）单元测试。

覆盖：平铺/错位格式 → 模板 eitia-cfr.html 期望的 V5 结构化形态；
已结构化数据幂等。模板是唯一契约（见 render_report.py normalize_report 注释）。
不触达 jinja2 渲染，仅测数据形态转换。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "agents"
    / "discover"
    / "client-finder"
    / "scripts"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import render_report  # type: ignore[import-not-found]  # noqa: E402  # 脚本目录运行期经 sys.path 注入，mypy 静态不可见


def _flat_client(rank: int, name: str, display: str) -> dict[str, Any]:
    return {
        "fullname": name,
        "display_name": display,
        "score": 8.5 - rank * 0.5,
        "rank": rank,
        "tags": ["A股上市", "龙头"],
        "oneliner": f"{display}一句话定位",
        "basic_table": [
            {"label": "法定代表人", "value": "张三"},
            {"label": "注册资本", "value": "1亿元"},
        ],
        "equity_section": "实控人为XX。来源：公开搜索。",
        "match_highlights": ["技术匹配度高", "需求明确"],
        "match_risks": ["认证周期长"],
        "veto_check": [{"item": "失信", "result": "未触发"}, {"item": "破产", "result": "未触发"}],
        "contacts_intro": "决策人公开信息有限",
        "decision_insight": "建议技术切入",
        "decision_chain": [
            {"name": "张三", "note": "最高决策人", "source": "企查查", "title": "董事长"}
        ],
        "signal_insight": "近期扩产",
        "match_subscore_1": {
            "name": "采购规模",
            "score": 9,
            "source": "企查查",
            "basis": "年营收大",
        },
        "procurement": "供应商体系开放，采购量大",
        "contact_cards": [
            {"channel": "企查查工商登记", "name": "张三", "note": "最高决策人", "title": "董事长"}
        ],
        "signals": [{"date": "2026Q1", "signal": "营收+50%", "source": "财报", "type": "规模"}],
        "engagement": {
            "approach": "1通过展会接触2重点对接采购3提供方案",
            "key_message": "对标国际品牌的国产替代",
            "priority": "高",
        },
        "competition": "已供货竞品：某厂商。",
        "competitive_landscape": "某厂商份额高",
        "risks": [{"type": "竞争激烈", "description": "已有竞品进入"}],
    }


def _flat_report() -> dict[str, Any]:
    return {
        "cover": {
            "title": "报告",
            "subtitle": "副标题",
            "product": "连接器",
            "scope": "全国",
            "date": "2026-08-24",
            "data_date": "2026-08-24",
            "summary": "筛选出 5 家潜在客户",
        },
        "l0": {
            "funnel": "需求澄清产品=连接器",
            "signal_heatmap": "浪潮信息存货+49%信号极强超聚变IPO过会信号强",
            "top_table": [{"name": "A公司", "rank": 1, "score": 8.0, "status": "推荐"}],
            "top_n": 5,
            "industry": {
                "market_size": "2024年全球服务器市场规模2164亿美元",
                "eitia_position": "产业链中游服务器整机制造商成都派兹处于上游元器件层",
                "customer_map": "A公司服务器全球第二B公司X86继承者",
                "competitive_landscape": "华丰科技高速背板一供",
                "key_trends": ["AI带动高速连接器需求", "国产替代加速"],
            },
        },
        "clients": [
            _flat_client(1, "A股份有限公司", "A公司"),
            _flat_client(2, "B股份有限公司", "B公司"),
        ],
        "appendix": {
            "data_log": [
                {"tool": "web_search", "call_count": "10次", "usage": "搜索", "note": "无"}
            ],
            "scoring_method": "八维评分采购规模15%各维0-10分信用安全小于3.0排除",
            "glossary": [{"term": "JDM模式", "definition": "联合设计制造"}],
            "disclaimer": "本报告基于公开信息。",
            "version": "V5",
        },
    }


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_normalize_no_python_repr_leak() -> None:
    data = render_report.normalize_report(_flat_report())
    client = data["clients"][0]
    assert isinstance(client["tags"], str) and "<span" in client["tags"]
    assert isinstance(client["basic_table"], str) and "<tr" in client["basic_table"]
    assert isinstance(client["veto_check"], str) and "<span" in client["veto_check"]
    assert isinstance(data["appendix"]["glossary"], str) and "<dt>" in data["appendix"]["glossary"]
    assert (
        isinstance(data["appendix"]["data_log"], str) and "<table" in data["appendix"]["data_log"]
    )
    assert isinstance(data["l0"]["top_table"], str) and "<table" in data["l0"]["top_table"]
    assert isinstance(data["clients"][0]["decision_chain"], str)
    assert "{" not in data["clients"][0]["decision_chain"]


def test_normalize_customer_map_split_by_client_name() -> None:
    data = render_report.normalize_report(_flat_report())
    rows = data["l0"]["industry"]["customer_map"]
    assert isinstance(rows, list)
    assert [r["description"] for r in rows] == ["服务器全球第二", "X86继承者"]
    assert rows[0]["potential"] == "高"
    assert rows[1]["potential"] == "中"


def test_normalize_client_struct_filled() -> None:
    data = render_report.normalize_report(_flat_report())
    c = data["clients"][0]
    assert c["procurement"]["estimate_range"] == "数据受限"
    assert c["procurement"]["evidence_items"]
    assert c["contact_cards"][0]["source"] == "企查查工商登记"
    assert c["contact_cards"][0]["bio"] == "最高决策人"
    assert c["signals"][0]["detail"] == "营收+50%"
    assert c["signals"][0]["level"] == "green"
    assert c["engagement"]["positioning"] == "对标国际品牌的国产替代"
    assert c["engagement"]["value_props"] == ["通过展会接触", "重点对接采购", "提供方案"]
    assert c["competition"]["current_supplier_inference"] == "已供货竞品：某厂商。"
    assert c["risks"][0]["title"] == "竞争激烈"
    assert c["risks"][0]["detail"] == "已有竞品进入"


def test_normalize_match_subscore_maps_flat_keys() -> None:
    data = render_report.normalize_report(_flat_report())
    ms = data["clients"][0]["match_subscore_1"]
    assert ms["label"] == "采购规模"
    assert ms["score"] == 9
    assert ms["raw_data"] == "年营收大"
    assert ms["source"] == "企查查"


def test_normalize_scoring_method_adds_sections() -> None:
    data = render_report.normalize_report(_flat_report())
    text = str(data["appendix"]["scoring_method"])
    assert "§B.1" in text and "§B.3" in text


def test_normalize_is_idempotent() -> None:
    once = render_report.normalize_report(_flat_report())
    twice = render_report.normalize_report(once)
    assert _dump(once) == _dump(twice)


def test_normalize_keeps_already_structured_data() -> None:
    structured = render_report.normalize_report(_flat_report())
    structured["clients"][0]["tags"] = '<span class="client-tag">既有HTML</span>'
    structured["clients"][0]["basic_table"] = "<table><tr><td>既有表格</td></tr></table>"
    structured["l0"]["industry"]["customer_map"] = [
        {
            "sub_industry": "交换机",
            "description": "直接用户",
            "potential": "高",
            "reason": "高速互连",
        }
    ]
    again = render_report.normalize_report(structured)
    assert again["clients"][0]["tags"] == '<span class="client-tag">既有HTML</span>'
    assert again["clients"][0]["basic_table"] == "<table><tr><td>既有表格</td></tr></table>"
    assert again["l0"]["industry"]["customer_map"][0]["sub_industry"] == "交换机"


def test_normalize_guarantees_cover_and_appendix_contract() -> None:
    report = _flat_report()
    del report["cover"]
    del report["appendix"]
    data = render_report.normalize_report(report)
    assert isinstance(data["cover"], dict)
    assert isinstance(data["appendix"], dict)
    assert data["appendix"]["version"] == "V1"
    # 缺 product 时 main 文件名兜底「未命名产品」（.get 路径不崩溃）
    product = data.get("cover", {}).get("product") or "未命名产品"
    assert product == "未命名产品"


def test_render_survives_missing_cover_product_and_version(tmp_path: Path) -> None:
    """平台实测失败场景：LLM 输出缺 cover.product / appendix.version，main 不得崩溃。"""
    report = _flat_report()
    del report["cover"]["product"]
    del report["appendix"]["version"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    env.update({"WORKSPACE_DIR": str(tmp_path), "SKILL_ROOT_DIR": str(_SCRIPTS_DIR.parent)})
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "render_report.py"), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "报告已生成" in result.stdout


def test_render_survives_missing_cover_and_appendix(tmp_path: Path) -> None:
    """更极端场景：cover/appendix 整个缺失，main 仍不崩溃并产出报告。"""
    report = _flat_report()
    del report["cover"]
    del report["appendix"]
    path = tmp_path / "bad2.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    env.update({"WORKSPACE_DIR": str(tmp_path), "SKILL_ROOT_DIR": str(_SCRIPTS_DIR.parent)})
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "render_report.py"), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "报告已生成" in result.stdout


def test_normalize_report_non_dict_input_returns_empty() -> None:
    """非 dict 入参（数组/标量）不崩溃，返回空对象交给容错渲染。"""
    assert render_report.normalize_report([1, 2, 3]) == {}
    assert render_report.normalize_report("字符串") == {}
    assert render_report.normalize_report(None) == {}


def test_render_rejects_non_object_json_file(tmp_path: Path) -> None:
    """argv 文件顶层是数组而非对象：友好报错退出，不抛裸异常。"""
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    env = os.environ.copy()
    env.update({"WORKSPACE_DIR": str(tmp_path), "SKILL_ROOT_DIR": str(_SCRIPTS_DIR.parent)})
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "render_report.py"), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert result.returncode == 1
    assert "必须是 JSON 对象" in result.stdout
