"""ContextAssembler：统一从事实来源构建 AgentContext（agent-context-plane-spec §5.1）。

单一动机：把「加载会话历史 / 消息附件 → 确定性裁剪 → 生成带来源与版本的
AgentContext」收敛为唯一入口，替代调用方分散维护的历史拼接逻辑。

边界（P1#9）：本模块属 Harness 上下文编译器——回答「本轮选择哪些事实、如何裁剪」；
事实来源（会话 / 附件）经 `app.environment.context.ports` 抽象注入，具体存储适配由
组合根装配。不负责（规范 §5.1）：LLM 调用、工具调用、Workflow 路由、数据库结构
迁移、SSE 输出、修改 Run 控制状态。构造函数只依赖抽象端口。
"""

from __future__ import annotations

from app.environment.context.models import (
    AgentContext,
    AttachmentContext,
    ContextAssemblyOptions,
    ContextConstraints,
    ContextIdentity,
    ContextMessage,
    ContextSummary,
    ConversationContext,
    CurrentInput,
    MemoryContext,
    WorkflowContext,
)
from app.environment.context.ports import AttachmentContextPort, ConversationContextPort
from app.shared.utils.sanitize import truncate


def _range_label(message_ids: list[str]) -> str:
    """消息覆盖范围标签：无角色级 ID 时留空，不伪造区间。"""
    if not message_ids:
        return ""
    return f"{message_ids[0]}..{message_ids[-1]}"


def _truncated_copy(message: ContextMessage, max_chars: int) -> ContextMessage:
    """截断单条超预算消息并保留截断标记（规范 §6.2）。"""
    return message.model_copy(
        update={
            "content": truncate(message.content, max_length=max_chars),
            "metadata": {**message.metadata, "truncated": True},
        }
    )


def _apply_char_budget(messages: list[ContextMessage], max_chars: int) -> list[ContextMessage]:
    """从最近往更早保留消息，直到字符预算用完；更早的消息整条丢弃（规范 §6.1）。"""
    kept: list[ContextMessage] = []
    budget = max_chars
    for message in reversed(messages):
        cost = len(message.content)
        if cost <= budget:
            kept.append(message)
            budget -= cost
            continue
        if not kept:
            # 最近一条自身超预算：截断保留并标记，避免上下文被清空。
            kept.append(_truncated_copy(message, budget))
        break
    kept.reverse()
    return kept


class ContextAssembler:
    """AgentContext 的唯一构造入口（规范 §5.1）。

    端口缺失时对应区块为空，不抛异常：无 DB 环境（单测 / 无会话服务）仍可装配。
    """

    def __init__(
        self,
        *,
        conversation: ConversationContextPort | None = None,
        attachments: AttachmentContextPort | None = None,
        options: ContextAssemblyOptions | None = None,
    ) -> None:
        self._conversation = conversation
        self._attachments = attachments
        self._default_options = options or ContextAssemblyOptions()

    async def assemble(
        self,
        identity: ContextIdentity,
        current_input: CurrentInput,
        *,
        workflow: WorkflowContext | None = None,
        constraints: ContextConstraints | None = None,
        options: ContextAssemblyOptions | None = None,
    ) -> AgentContext:
        """构建上下文快照：身份 + 当前输入 + 历史 + 附件 + 阶段 + 约束。"""
        effective = options or self._default_options
        messages = self._trim(await self._load_messages(identity, effective), effective)
        return AgentContext(
            identity=identity,
            current_input=current_input,
            conversation=self._build_conversation(identity, messages, effective),
            attachments=await self._load_attachments(identity, current_input),
            memory=MemoryContext(),
            workflow=workflow or WorkflowContext(),
            constraints=constraints or ContextConstraints(),
            version=identity.context_version,
        )

    async def _load_messages(
        self, identity: ContextIdentity, options: ContextAssemblyOptions
    ) -> list[ContextMessage]:
        if self._conversation is None or not identity.conversation_id:
            return []
        return await self._conversation.load_recent_messages(
            account_id=identity.account_id,
            conversation_id=identity.conversation_id,
            limit=max(1, options.max_recent_messages),
        )

    async def _load_attachments(
        self, identity: ContextIdentity, current_input: CurrentInput
    ) -> AttachmentContext:
        """仅在当前输入声明了 file_ids 时读取附件引用（阶段五接入契约后生效）。"""
        if self._attachments is None or not current_input.file_ids:
            return AttachmentContext()
        files = await self._attachments.load_message_attachments(
            account_id=identity.account_id,
            conversation_id=identity.conversation_id,
            file_ids=current_input.file_ids,
        )
        return AttachmentContext(files=files)

    def _trim(
        self, messages: list[ContextMessage], options: ContextAssemblyOptions
    ) -> list[ContextMessage]:
        """确定性裁剪：先取最近 N 条，再按字符预算从最近往更早保留（规范 §6.1）。"""
        kept = messages[-max(1, options.max_recent_messages) :]
        if options.max_context_chars <= 0:
            return kept
        return _apply_char_budget(kept, options.max_context_chars)

    def _build_conversation(
        self,
        identity: ContextIdentity,
        messages: list[ContextMessage],
        options: ContextAssemblyOptions,
    ) -> ConversationContext:
        ids = [message.message_id for message in messages if message.message_id]
        return ConversationContext(
            summary=self._build_summary(identity, messages, options),
            recent_messages=messages,
            message_refs=list(
                dict.fromkeys(message.source_ref for message in messages if message.source_ref)
            ),
            covered_message_range=_range_label(ids),
        )

    def _build_summary(
        self,
        identity: ContextIdentity,
        messages: list[ContextMessage],
        options: ContextAssemblyOptions,
    ) -> ContextSummary | None:
        """生成可追踪摘要（规范 §6.3）：记录来源、覆盖范围与上下文版本。"""
        if not options.summarize or not messages:
            return None
        recent = messages[-max(1, options.max_summary_messages) :]
        text = "\n".join(f"{message.role}: {message.content}" for message in recent)
        ids = [message.message_id for message in recent if message.message_id]
        return ContextSummary(
            summary=truncate(text, max_length=options.max_summary_chars)
            if options.max_summary_chars > 0
            else text,
            source="conversation",
            covered_message_ids=ids,
            covered_message_range=_range_label(ids),
            context_version=identity.context_version,
        )
