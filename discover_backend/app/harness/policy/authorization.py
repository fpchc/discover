"""行动授权（react-runtime-v2-architecture §11.1 授权层，P0 边界）。

单一动机：在 Action 执行前判定「当前账号是否有权触发此类副作用」，与
`check_action`（存在性 / 白名单 / schema / 重复无进展）正交。身份与风险在这里
收敛；参数是否合法仍归 Action Policy，二者分层、互不膨胀（§21 职责边界）。

首期（W1）只落地确定性授权：superuser 旁路 + 配置驱动的「需审批副作用」矩阵。
roles / data_scope / approval_state 仅作端口预留，权限码体系与 HITL 审批流接入
后再参与判定，当前不消费。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from app.config.settings import SideEffectType


class AuthorizationContext(BaseModel):
    """一次工具调用的授权上下文（身份与权限边界）。"""

    account_id: str = ""
    # 权限角色（首期预留，暂不参与判定；权限码体系接入后使用）
    roles: list[str] = Field(default_factory=list)
    # 超级用户（is_system）：旁路审批矩阵
    superuser: bool = False
    # 数据访问范围（首期预留，暂不参与判定）
    data_scope: str = ""
    # 审批状态（首期预留；HITL 审批流接入后使用）
    approval_state: str | None = None


class AuthorizationDecisionType(StrEnum):
    """授权结论：ALLOW 放行 / DENY 拒绝（含「需审批但未获授权」）。"""

    ALLOW = "allow"
    DENY = "deny"


class AuthorizationDecision(BaseModel):
    """授权判定结果：结构化结论 + 原因 + 面向模型的展示说明。"""

    decision: AuthorizationDecisionType
    reason_code: str = ""
    display_message: str = ""


class ActionAuthorizer(Protocol):
    """行动授权端口：只判定不执行（与 Action Policy 同层，DIP §6）。"""

    def authorize(
        self, *, ctx: AuthorizationContext, side_effect: SideEffectType, tool_name: str
    ) -> AuthorizationDecision: ...


class PolicyAuthorizer:
    """配置驱动的确定性授权器（W1）。

    判定顺序：superuser 旁路 → 副作用命中「需审批」集合 → DENY；否则 ALLOW。
    首期无审批流，「需审批」且无 approval_state 一律 DENY（fail-closed）。
    """

    def __init__(self, *, approval_required: set[SideEffectType]) -> None:
        self._approval_required = approval_required

    def authorize(
        self, *, ctx: AuthorizationContext, side_effect: SideEffectType, tool_name: str
    ) -> AuthorizationDecision:
        if ctx.superuser:
            return AuthorizationDecision(
                decision=AuthorizationDecisionType.ALLOW, reason_code="superuser_bypass"
            )
        if side_effect in self._approval_required:
            return AuthorizationDecision(
                decision=AuthorizationDecisionType.DENY,
                reason_code="approval_required",
                display_message=(
                    f"工具 {tool_name} 的副作用 {side_effect.value} 需人工审批，当前会话未获授权"
                ),
            )
        return AuthorizationDecision(decision=AuthorizationDecisionType.ALLOW, reason_code="ok")


__all__ = [
    "ActionAuthorizer",
    "AuthorizationContext",
    "AuthorizationDecision",
    "AuthorizationDecisionType",
    "PolicyAuthorizer",
]
