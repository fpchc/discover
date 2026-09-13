#!/usr/bin/env python3
"""Final QA 门禁校验器（gate_final_qa）：输出泄露 + 排版/长度/逐卡字数（阻断）。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码 = 未通过。
入参：{"answer": "<信息卡正文>"}
出参：{"passed": bool, "errors": [...], "warnings": [...]}

阻断级：answer 出现内部机制名（工具 / 脚本 / 文档 / 门禁 / 能力名）→ 泄露，判失败。

阻断级：
- 排版结构（card-format.md 禁例「整段纯散文」）：行首 `**` 加粗小标签行 < 2 行 →
  字段未逐条成行，视为排版不合格。
- 每张卡（按独立成行的 --- 分隔）450~550 字；低于/超过均判失败。
- 行内出现 --- 分隔符（前端会当字面文本显示；卡间分隔必须用独立成行 ---）。

用途：模型在输出信息卡前调用本门禁，校验可见 answer 不暴露技能内部信息 / 思考内容，
并强制三段式排版、字数区间与分隔符合规；不合格即判失败，须修复后重跑。
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

# 泄露黑名单：任何一项出现在可见 answer 中都视为泄露（阻断）。
# 注意：不得把「推断」「未检索到」等合法卡内容词加入黑名单。
LEAK_PATTERNS: list[str] = [
    # 脚本 / 文件名
    "score_calculator",
    "scoring-rules",
    "evidence-rules",
    "score_input",
    "scene-routing",
    "architecture",
    "golden_cases",
    # 门禁 / 流程术语
    "final_qa",
    "final qa",
    "门禁",
    "score trace",
    "八维评分",
    "候选池",
    "交叉验证",
    "证据等级",
    "动态补搜",
    "红线",
    "一票否决",
    "综合分",
    "维度分",
    # 数据能力 / 通道名
    "web_search",
    "enterprise_business",
    "enterprise_risk",
    "financial_data",
    "企业画像能力",
    "企业风险能力",
    "财务数据能力",
    "联网搜索",
    # 文件引用
    ".py",
    ".md",
    ".json",
]

# 字数区间（card-format.md §4：单卡 450~550 字，多企每张卡各自满足）
MIN_LENGTH = 450
MAX_LENGTH = 550
# 卡间分隔：独立成行的 ---（card-format.md 多企分隔唯一方式）
CARD_SEPARATOR_RE = re.compile(r"(?m)^\s*---\s*$")
# 排版结构红线（card-format.md 禁例「整段纯散文」）：行首 `**` 加粗小标签行至少 2 行
MIN_BOLD_LABEL_LINES = 2
BOLD_LABEL_LINE_RE = re.compile(r"^\s*\*\*")


def _strip_markup(text: str) -> str:
    """去掉加粗标记后再计字数（card-format.md §4：标签与加粗不重复计内容）。"""
    return text.replace("**", "")


def _split_cards(answer: str) -> list[str]:
    """按独立成行的 --- 切分多企信息卡；无分隔符时视为单卡。"""
    parts = CARD_SEPARATOR_RE.split(answer)
    cards = [part.strip() for part in parts if part.strip()]
    return cards or [answer]


def check(answer: str) -> tuple[list[str], list[str]]:
    """校验 answer，返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    lowered = answer.lower()
    for pattern in LEAK_PATTERNS:
        if pattern.lower() in lowered:
            errors.append(f"泄露内部机制名：{pattern}")

    # 行内 --- 分隔符：前端当字面文本显示，判失败（独立成行的 --- 渲染为分隔线）
    lines = answer.splitlines()
    if any("---" in line and line.strip() != "---" for line in lines):
        errors.append("发现行内 --- 分隔符：前端会当字面文本显示；卡间分隔请用独立成行的 ---")

    # 逐卡校验：多企时每张卡独立满足 450~550 字与加粗标签行数
    for card_index, card in enumerate(_split_cards(answer), start=1):
        card_len = len(_strip_markup(card))
        if card_len < MIN_LENGTH:
            errors.append(
                f"第 {card_index} 张卡 {card_len} 字，低于 {MIN_LENGTH} 字下限（至少一张卡）"
            )
        if card_len > MAX_LENGTH:
            errors.append(f"第 {card_index} 张卡 {card_len} 字，超过 {MAX_LENGTH} 字上限")
        card_lines = card.splitlines()
        bold_label_lines = [line for line in card_lines if BOLD_LABEL_LINE_RE.match(line)]
        if len(bold_label_lines) < MIN_BOLD_LABEL_LINES:
            errors.append(
                f"第 {card_index} 张卡排版不合格（整段纯散文/字段未逐条成行）："
                f"行首 `**` 加粗标签行仅 {len(bold_label_lines)} 行，"
                f"至少需要 {MIN_BOLD_LABEL_LINES} 行，见 card-format.md 三段式"
            )
    return errors, warnings


def main() -> None:
    try:
        data: dict[str, Any] = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {"passed": False, "errors": [f"JSON 解析失败: {exc}"], "warnings": []},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        print(
            json.dumps(
                {"passed": False, "errors": ["缺少 answer 或 answer 为空"], "warnings": []},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    errors, warnings = check(answer)
    passed = len(errors) == 0
    print(
        json.dumps(
            {"passed": passed, "errors": errors, "warnings": warnings},
            ensure_ascii=False,
            indent=2,
        )
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
