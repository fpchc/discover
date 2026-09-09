#!/usr/bin/env python3
"""Final QA 门禁校验器（gate_final_qa）：输出泄露（阻断）+ 排版/长度（警告）。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码 = 未通过。
入参：{"answer": "<信息卡正文>"}
出参：{"passed": bool, "errors": [...], "warnings": [...]}

阻断级：answer 出现内部机制名（工具 / 脚本 / 文档 / 门禁 / 能力名）→ 泄露，判失败。

警告级：
- 排版结构（card-format.md 禁例「整段纯散文」）：行首 `**` 加粗小标签行 < 2 行 →
  字段未逐条成行，仅提示不阻断（避免模型陷入重写死循环）。
- 总长低于 450 字（不足一张卡）；某段（空行分隔块）超过 550 字（疑似多卡挤一段/单卡超限）。
- 行内出现 --- 分隔符（前端会当字面文本显示；卡间分隔应空行或独立成行 ---）。

用途：模型在输出信息卡前调用本门禁，校验可见 answer 不暴露技能内部信息 / 思考内容；
排版结构仅作提示，不因排版不合格要求重写。
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

# 字数区间（card-format.md §4：单卡 450~550 字，多企每张各自满足）
MIN_LENGTH = 450
# 单段（空行分隔块）上限：超过 550 字 → 疑似多卡挤一段或单卡超限（仅警告）
MAX_PARAGRAPH_LENGTH = 550
# 排版结构红线（card-format.md 禁例「整段纯散文」）：行首 `**` 加粗小标签行至少 2 行
MIN_BOLD_LABEL_LINES = 2
BOLD_LABEL_LINE_RE = re.compile(r"^\s*\*\*")


def check(answer: str) -> tuple[list[str], list[str]]:
    """校验 answer，返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    lowered = answer.lower()
    for pattern in LEAK_PATTERNS:
        if pattern.lower() in lowered:
            errors.append(f"泄露内部机制名：{pattern}")

    # 排版结构（警告级）：整段纯散文 / 字段未逐条成行 → 仅提示不阻断（避免模型重写死循环）
    lines = answer.splitlines()
    bold_label_lines = [line for line in lines if BOLD_LABEL_LINE_RE.match(line)]
    if len(bold_label_lines) < MIN_BOLD_LABEL_LINES:
        warnings.append(
            "排版待改进（整段纯散文/字段未逐条成行）：行首 `**` 加粗标签行仅 "
            f"{len(bold_label_lines)} 行，建议至少 {MIN_BOLD_LABEL_LINES} 行"
            "——每个小标签独占一行，见 card-format.md 三段式"
        )

    # 长度（警告级）：总长过低 → 不足一张卡；某段过长 → 多卡挤一段/单卡超限
    if len(answer) < MIN_LENGTH:
        warnings.append(f"正文 {len(answer)} 字，低于 {MIN_LENGTH} 字下限（至少一张卡）")
    for i, paragraph in enumerate(re.split(r"\n\s*\n", answer), start=1):
        para_len = len(paragraph.strip())
        if para_len > MAX_PARAGRAPH_LENGTH:
            warnings.append(
                f"第 {i} 段 {para_len} 字，超过 {MAX_PARAGRAPH_LENGTH} 字上限"
                "（疑似多卡挤一段或单卡超限，卡与卡之间应空行分隔）"
            )

    # 行内 --- 分隔符：前端当字面文本显示，仅警告（独立成行的 --- 渲染为分隔线）
    if any("---" in line and line.strip() != "---" for line in lines):
        warnings.append(
            "发现行内 --- 分隔符：前端会当字面文本显示；卡间分隔请用空行，或把 --- 独立成行"
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
