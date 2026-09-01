"""腾讯联网搜索 MCP 服务配置（pydantic-settings）。

端点 URL / 令牌 / 阈值一律进配置（CLAUDE.md §5）：环境变量可覆盖，默认值即配置默认。
平台经 Streamable HTTP 连接本服务时，以 `TENCENT_MCP_TOKEN` 作 Bearer 校验。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TencentMCPSettings(BaseSettings):
    """腾讯联网搜索 MCP 服务配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MCP 服务鉴权：平台以 `Authorization: Bearer <此值>` 连接；未配置则拒绝一切请求（fail-closed）
    tencent_mcp_token: str = ""
    # 腾讯 WSA 联网搜索
    wsa_api_key: str = ""
    wsa_search_url: str = "https://api.wsa.cloud.tencent.com/SearchPro"
    # 出站 HTTP 超时（秒）
    http_timeout_seconds: float = 30.0
    # 服务监听地址：本地默认 127.0.0.1:10001；docker 内须设 0.0.0.0 供同网络容器访问
    tencent_mcp_host: str = "0.0.0.0"
    tencent_mcp_port: int = 10001
    # 日志观测：查询关键词在日志中的截断长度（CLAUDE.md §5 阈值进配置）
    log_query_max_chars: int = 100
