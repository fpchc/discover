#!/usr/bin/env python3
"""Final QA 门禁校验器（gate_final_qa）：输出泄露 + 长度校验。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码 = 未通过。
入参：{"answer": "<信息卡正文>"}
出参：{"passed": bool, "errors": [...], "warnings": [...]}

阻断级：answer 出现内部机制名（工具 / 脚本 / 文档 / 门禁 / 能力名）→ 泄露，判失败。
警告级：超 450 字或低于 200 字 → 仅提示，不阻断（避免模型陷入重写循环）。

用途：模型在输出信息卡前调用本门禁，校验可见 answer 不暴露技能内部信息 / 思考内容。
信息卡已去模板化：不做固定分块结构校验（结构由内容自然决定）。
"""

from __future__ import annotations

import json
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

MIN_LENGTH = 200
MAX_LENGTH = 450


def check(answer: str) -> tuple[list[str], list[str]]:
    """校验 answer，返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    lowered = answer.lower()
    for pattern in LEAK_PATTERNS:
        if pattern.lower() in lowered:
            errors.append(f"泄露内部机制名：{pattern}")
    if len(answer) < MIN_LENGTH:
        warnings.append(f"正文 {len(answer)} 字，低于 {MIN_LENGTH} 字下限")
    if len(answer) > MAX_LENGTH:
        warnings.append(f"正文 {len(answer)} 字，超过 {MAX_LENGTH} 字上限")
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
