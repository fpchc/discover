"""技能包管理路由按配置装配的单测（无 DB / 无网络）。

`/admin/packages` 只在 `agent_package_source == "database"` 时注册：
filesystem 模式下 SkillPackageService 不装配，注册路由会导致请求命中
AssertionError（500）。本测试锁定「按配置是否暴露路由」的装配契约。
"""

from __future__ import annotations

from app.bootstrap.application import create_app
from app.config.settings import Settings
from fastapi import FastAPI


def _admin_package_paths(app: FastAPI) -> set[str]:
    """收集 OpenAPI 中 /api/v1/admin/packages 开头的路径。"""
    return {path for path in app.openapi()["paths"] if path.startswith("/api/v1/admin/packages")}


def test_admin_packages_routes_only_registered_in_database_mode() -> None:
    filesystem_app = create_app(
        Settings(_env_file=None, logging_enabled=False, agent_package_source="filesystem")
    )
    database_app = create_app(
        Settings(_env_file=None, logging_enabled=False, agent_package_source="database")
    )

    assert _admin_package_paths(filesystem_app) == set()
    assert len(_admin_package_paths(database_app)) > 0
