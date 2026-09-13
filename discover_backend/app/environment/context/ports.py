"""上下文来源端口（agent-context-plane-spec §5.1 / §11 阶段二）。

单一动机：让 ContextAssembler 只依赖调用方拥有的抽象，具体实现（会话服务、
文件服务）在组合根装配（platform-architecture-spec §2 依赖方向）。

端口一律 async：实现侧会触达数据库或存储，禁止在 async 路径做阻塞 I/O。
"""

from __future__ import annotations

from typing import Protocol

from app.environment.context.models import ContextMessage, FileRef


class ConversationContextPort(Protocol):
    """会话历史来源（唯一事实来源：ConversationService / Conversation Store）。

    实现必须按 `account_id` 校验会话归属，跨账号不得返回任何内容。
    """

    async def load_recent_messages(
        self, *, account_id: str, conversation_id: str, limit: int
    ) -> list[ContextMessage]: ...


class AttachmentContextPort(Protocol):
    """消息附件来源（唯一事实来源：FileService / upload_files）。

    只返回引用与元数据，不返回文件正文；归属与访问范围校验由实现负责。
    消息附件契约与文件-消息关联属后续阶段（规范 §11 阶段五），本阶段默认不接线。
    """

    async def load_message_attachments(
        self, *, account_id: str, conversation_id: str, file_ids: list[str]
    ) -> list[FileRef]: ...
