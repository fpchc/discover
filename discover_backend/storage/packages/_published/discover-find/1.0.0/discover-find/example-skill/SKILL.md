---
skill_id: example-skill
version: "1.0.0"
description: 请填写这个技能的工作流与交付物
scope:
  applies: 请填写该技能适用的具体任务
  does_not_apply: 请填写该技能不适用的任务
keywords: []
documents:
  - path: references/guide.md
    when: 执行本技能工作流时
    preload: true
templates:
  - path: templates/output.md
    purpose: 最终输出的结构模板
---
# 技能工作流

在这里编写可执行的工作步骤、约束和降级策略。

## 执行要求

1. 先确认输入是否满足适用条件。
2. 按步骤执行并记录必要依据。
3. 输出遵循 `templates/output.md` 的结构。

## 最终提交契约

完成任务后必须调用 `submit_final_answer`，并提交完整最终答复。不得把内部执行过程写入最终答复。