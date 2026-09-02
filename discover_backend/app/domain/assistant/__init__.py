"""助手选择域：用户可选助手目标 + 只读目录。

选择模型（AssistantTarget / TargetType / SelectionSource）跨 runtime /
conversation / events 共享；解析（AssistantResolver）已随「解析服务 Runtime」
原则移至 runtime/resolver。catalog 不在此包级导出——它反向依赖 skill 注册表，
导出会引入 assemble ⇄ registry 循环（经 app.domain 门面访问）。
"""

from app.domain.assistant.models import (
    GENERIC_ASSISTANT_ID,
    GENERIC_ASSISTANT_NAME,
    AssistantTarget,
    SelectionSource,
    TargetType,
)

__all__ = [
    "GENERIC_ASSISTANT_ID",
    "GENERIC_ASSISTANT_NAME",
    "AssistantTarget",
    "SelectionSource",
    "TargetType",
]
