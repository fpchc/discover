"""会话域（domain/conversation）：对话与回合的领域词汇。

跨边界 DTO（ConversationSession / TurnRecord 等）在 `app/application/dto/`；
用例编排（ConversationService / TurnRecorder）在 `app/application/conversation/`；
持久化实现（ORM + 仓储）在 `app/infrastructure/database/`。
"""

__all__: list[str] = []
