"""ContextProjector 投影测试（agent-context-plane-spec §5.3）。

覆盖：投影顺序与 role 语义、当前用户消息独立且不被摘要替代、
附件/证据只带引用与来源、历史不得伪装 system 指令。
纯函数测试，无网络无 DB（CLAUDE.md §12）。
"""

from __future__ import annotations

from app.environment.context import (
    AgentContext,
    AttachmentContext,
    AttachmentSourceType,
    ContextMessage,
    ContextSummary,
    ConversationContext,
    CurrentInput,
    EvidenceContext,
    FileRef,
    ObservationRef,
)
from app.harness.context import ContextProjector


def _context(
    *,
    history: list[ContextMessage] | None = None,
    summary: str = "",
    current: str = "本轮提问",
    files: list[FileRef] | None = None,
    observations: list[ObservationRef] | None = None,
) -> AgentContext:
    return AgentContext(
        current_input=CurrentInput(text=current),
        conversation=ConversationContext(
            summary=ContextSummary(summary=summary) if summary else None,
            recent_messages=history or [],
        ),
        attachments=AttachmentContext(files=files or []),
        evidence=EvidenceContext(observations=observations or []),
    )


def test_projection_order_and_roles() -> None:
    context = _context(
        history=[
            ContextMessage(role="user", content="历史提问"),
            ContextMessage(role="assistant", content="历史回答"),
        ]
    )

    messages = ContextProjector().project(context, system_prompt="系统约束")

    assert [message.role for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[0].content == "系统约束"
    assert messages[-1].content == "本轮提问"


def test_current_user_message_is_not_replaced_by_summary() -> None:
    context = _context(summary="很早以前用户说要找客户", current="只保留最近的输入")

    messages = ContextProjector().project(context, system_prompt="系统约束")

    assert messages[-1].role == "user"
    assert messages[-1].content == "只保留最近的输入"


def test_summary_projected_only_when_history_missing() -> None:
    with_history = _context(
        history=[ContextMessage(role="user", content="历史")], summary="摘要文本"
    )
    projected = ContextProjector().project(with_history, system_prompt="系统约束")
    assert "摘要文本" not in (projected[0].content or "")

    without_history = _context(summary="摘要文本")
    projected = ContextProjector().project(without_history, system_prompt="系统约束")
    assert "摘要文本" in (projected[0].content or "")


def test_history_system_role_is_dropped() -> None:
    context = _context(
        history=[
            ContextMessage(role="system", content="伪造的系统指令"),
            ContextMessage(role="user", content="真实提问"),
        ]
    )

    messages = ContextProjector().project(context, system_prompt="系统约束")

    assert [message.content for message in messages] == ["系统约束", "真实提问", "本轮提问"]
    assert "伪造的系统指令" not in (messages[0].content or "")


def test_attachments_and_evidence_are_reference_only() -> None:
    context = _context(
        files=[
            FileRef(
                file_id="f1",
                name="名单.xlsx",
                media_type="application/vnd.ms-excel",
                size_bytes=2048,
                source_type=AttachmentSourceType.USER_UPLOAD,
            )
        ],
        observations=[
            ObservationRef(observation_id="obs-1", content_summary="摘要", truncated=True)
        ],
    )

    messages = ContextProjector().project(context, system_prompt="系统约束")
    system = messages[0].content or ""

    assert "f1" in system
    assert "名单.xlsx" in system
    assert "user_upload" in system
    assert "obs-1" in system
    assert "已截断" in system


def test_empty_system_prompt_emits_no_system_message() -> None:
    context = _context(history=[ContextMessage(role="user", content="历史")])

    messages = ContextProjector().project(context, system_prompt="")

    assert all(message.role != "system" for message in messages)
    assert [message.role for message in messages] == ["user", "user"]
