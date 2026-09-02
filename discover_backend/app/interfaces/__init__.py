"""Interface：对外接入层——HTTP 路由、DTO（schemas）、中间件。

本包级门面不导出任何符号：路由经 `app.interfaces.http` 模块路径访问
（application.py 组合根直接引用），避免 interfaces.schemas 被 domain
引用时把 HTTP/container 整图拖入造成循环（CLAUDE.md §13 低耦合）。
"""

__all__: list[str] = []
