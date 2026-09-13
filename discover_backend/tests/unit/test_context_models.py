"""Agent 上下文模型层测试（agent-context-plane-spec §4 / §11 阶段一）。

覆盖：序列化 round-trip、默认值、版本字段、引用字段与边界约束。
纯模型测试，无网络无 DB（CLAUDE.md §12）。
"""

from __future__ import annotations

import pytest
from app.environment.context import (
    AgentContext,
    AttachmentContext,
    AttachmentSourceType,
    ContextDelta,
    ContextIdentity,
    ContextMessage,
    ContextSummary,
    ConversationContext,
    CurrentInput,
    EvidenceContext,
    FileRef,
    MemoryUpdate,
    ObservationRef,
)
from pydantic import ValidationError


def _context() -> AgentContext:
    return AgentContext(
        identity=ContextIdentity(
            run_id="run-1",
            conversation_id="conv-1",
            message_id="msg-1",
            account_id="acc-1",
            phase_instance_id="client-finder",
            context_version=3,
        ),
        current_input=CurrentInput(text="找客户", message_id="msg-1", file_ids=["f1"]),
        conversation=ConversationContext(
            summary=ContextSummary(summary="用户: 你好", source="conversation"),
            recent_messages=[ContextMessage(role="user", content="你好")],
            message_refs=["conversation:conv-1"],
        ),
        attachments=AttachmentContext(
            files=[FileRef(file_id="f1", name="名单.xlsx", size_bytes=128)],
        ),
        evidence=EvidenceContext(
            observations=[ObservationRef(observation_id="obs-1", content_summary="摘要")]
        ),
        version=3,
    )


def test_agent_context_round_trip() -> None:
    context = _context()
    restored = AgentContext.model_validate(context.model_dump())
    assert restored == context
    assert restored.version == 3
    assert restored.identity.context_version == 3


def test_agent_context_current_input_is_required() -> None:
    with pytest.raises(ValidationError):
        AgentContext.model_validate({})  # type: ignore[arg-type]  # 缺 current_input


def test_file_ref_defaults_to_user_upload_and_keeps_no_body() -> None:
    file_ref = FileRef(file_id="f1")
    assert file_ref.source_type == AttachmentSourceType.USER_UPLOAD
    # 引用模型只带元数据：不得出现正文 / 二进制字段
    assert "content" not in FileRef.model_fields
    assert "bytes" not in FileRef.model_fields


def test_context_message_role_is_limited_to_projectable_roles() -> None:
    """observation / artifact 角色属目标态（规范 §4.4），当前不得伪装成已支持。"""
    with pytest.raises(ValidationError):
        ContextMessage.model_validate({"role": "observation", "content": "x"})


def test_context_delta_round_trip() -> None:
    delta = ContextDelta(
        messages=[ContextMessage(role="assistant", content="结果")],
        observations=[ObservationRef(observation_id="obs-1", truncated=True)],
        memory_updates=[MemoryUpdate(text="客户偏好线上沟通", source_ref="obs-1")],
        limitations=["数据源降级"],
    )
    restored = ContextDelta.model_validate(delta.model_dump())
    assert restored == delta
    assert restored.observations[0].truncated is True


def test_agent_context_has_no_unbounded_root_dict() -> None:
    """统一上下文模型不得退化为无边界 dict[str, object]（规范 §4.1 / §10.9）。"""
    assert set(AgentContext.model_fields) == {
        "current_input",
        "identity",
        "conversation",
        "attachments",
        "memory",
        "workflow",
        "evidence",
        "artifacts",
        "constraints",
        "version",
    }
