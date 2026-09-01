"""本地自建 MCP 服务聚合包。

腾讯（tencent_mcp，10001）与东方财富（eastmoney_mcp，10002）两个独立本地 MCP 服务
统一收拢在本包下（CLAUDE.md §13.1：职责单一，服务边界不混装，各占端口与令牌）。
运行：python -m local_mcp.tencent_mcp.main / python -m local_mcp.eastmoney_mcp.main。
"""

__all__ = ["eastmoney_mcp", "tencent_mcp"]
