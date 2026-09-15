"""回合上下文装配（接入层胶水，agent-context-plane-spec §5.1 / §5.4）。

单一动机：把「服务容器里的来源端口 + 会话身份 + 本轮输入」组装成结构化
`AgentContext` 并投影为 LLM 消息。专家 ReAct 与通用对话两条路径共用同一套
装配与投影规则，不再各自维护历史拼接逻辑（规范 §5.4）。

职责边界：只做装配与投影调用，不做鉴权判断、不发事件、不落库、不修改 Run 状态。
依赖方向：interfaces → domain/context（装配器、投影器）+ capabilities/llm（消息模型）。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.application.dto import ConversationSession
from app.application.services import AppServices
from app.config.settings import Settings
from app.environment.context import (
    AgentContext,
    ContextAssemblyOptions,
    ContextIdentity,
    CurrentInput,
)
from app.harness.context import ContextAssembler, ContextProjector
from app.llm.models import ChatMessage


class TurnContextRequest(BaseModel):
    """本轮上下文装配输入（跨边界 DTO）。"""

    session: ConversationSession
    user_input: str
    run_id: str
    # 当前阶段标识（单阶段专家路径取技能 id；通用对话为空）
    phase_instance_id: str = ""
    # 专家 ReAct 路径使用专家上下文预算；通用对话沿用完整历史窗口
    expert: bool = False
    # 调试预览等无持久化会话场景关闭历史查询
    load_history: bool = True


class TurnContext(BaseModel):
    """装配结果：结构化上下文 + 兼容摘要 + 投影入口。"""

    context: AgentContext
    history_summary: str = ""

    def messages(self, *, system_prompt: str) -> list[ChatMessage]:
        """投影为 LLM 消息：system + 历史消息（保留 role）+ 当前用户消息。"""
        return ContextProjector().project(self.context, system_prompt=system_prompt)


def _options(settings: Settings, *, expert: bool) -> ContextAssemblyOptions:
    """确定性裁剪预算（规范 §6.1）：专家路径沿用既有上下文摘要预算。"""
    if not expert:
        return ContextAssemblyOptions(
            max_recent_messages=settings.history_max_messages,
            summarize=False,
        )
    return ContextAssemblyOptions(
        max_recent_messages=settings.agent_context_summary_max_messages,
        max_context_chars=settings.agent_context_summary_max_chars,
        max_summary_messages=settings.agent_context_summary_max_messages,
        max_summary_chars=settings.agent_context_summary_max_chars,
    )


async def build_turn_context(services: AppServices, request: TurnContextRequest) -> TurnContext:
    """装配本轮 AgentContext（装配器缺失时退化为无历史的上下文）。

    装配器缺失有两种情况：容器未启动（测试替身 / 无 DB 环境），或未来装配层
    改为按需注入；两种都退化为「无历史上下文」，不阻断回合执行。
    """
    if not request.load_history:
        assembler = ContextAssembler(options=_options(services.settings, expert=request.expert))
    else:
        configured = getattr(services, "context_assembler", None)
        assembler = configured if isinstance(configured, ContextAssembler) else ContextAssembler()

    context = await assembler.assemble(
        ContextIdentity(
            run_id=request.run_id,
            conversation_id=request.session.conversation_id,
            account_id=request.session.account_id,
            phase_instance_id=request.phase_instance_id,
        ),
        CurrentInput(text=request.user_input),
        options=_options(services.settings, expert=request.expert),
    )
    summary = context.conversation.summary
    return TurnContext(context=context, history_summary=summary.summary if summary else "")
