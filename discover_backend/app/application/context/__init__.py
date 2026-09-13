"""上下文来源端口适配器：把业务事实来源（会话/文件）适配成环境端口。

适配器属于「业务侧适配到环境契约」，因此住在 application，而不是 environment
——环境不认识业务服务。
"""

from app.application.context.adapters import ConversationContextAdapter

__all__ = ["ConversationContextAdapter"]
