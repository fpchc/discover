"""应用层数据契约（跨边界 DTO）：会话/文件/账号的 pydantic 模型。

HTTP 请求/响应与 SSE 帧（对外协议形状）在 `app.interfaces.schemas`；
持久化载体为 infrastructure 的 ORM（CLAUDE.md §3）。
"""

from app.application.dto.auth import (
    AccountRecord,
    AccountStatus,
    AvatarConfig,
    ChangePasswordRequest,
    DailyUsage,
    ElecnestLoginRequest,
    ElecnestUserInfo,
    ElecnestUserInfoResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    PlatformTokenClaims,
    RefreshTokenRequest,
    UpdateAccountRequest,
    UserType,
    UserUsage,
)
from app.application.dto.conversations import (
    ConversationRecord,
    ConversationSession,
    ConversationStatus,
    DailyUsageItem,
    MessageRecord,
    MessageStatus,
    TurnRecord,
    TurnStartRecord,
    TurnUsage,
    UsageAggregate,
)
from app.application.dto.files import ArtifactRecord, FileResponse, UploadConfig

__all__ = [
    "AccountRecord",
    "AccountStatus",
    "ArtifactRecord",
    "AvatarConfig",
    "ChangePasswordRequest",
    "ConversationRecord",
    "ConversationSession",
    "ConversationStatus",
    "DailyUsage",
    "DailyUsageItem",
    "ElecnestLoginRequest",
    "ElecnestUserInfo",
    "ElecnestUserInfoResponse",
    "FileResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutRequest",
    "MessageRecord",
    "MessageStatus",
    "PlatformTokenClaims",
    "RefreshTokenRequest",
    "TurnRecord",
    "TurnStartRecord",
    "TurnUsage",
    "UpdateAccountRequest",
    "UploadConfig",
    "UsageAggregate",
    "UserType",
    "UserUsage",
]
