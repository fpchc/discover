"""技能包管理路由（管理员在线修改 / 校验 / 发布 / 回滚）。

仅超级用户可访问（require_superuser）。职责边界：只做参数提取与转调
SkillPackageService，不承载业务规则。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.application.dto.auth import AccountRecord
from app.application.dto.skill_packages import (
    CreateDraftRequest,
    DebugPreviewRequest,
    PackageDetail,
    PackageFile,
    PackageSummary,
    PreviewResult,
    PublishedPackage,
    RollbackRequest,
    SaveFileRequest,
    ToolSmokeRequest,
    ToolSmokeResult,
    ValidateResult,
)
from app.application.services import AppServices
from app.application.skill_package.debug import run_draft_preview, run_tool_smoke
from app.interfaces.http.auth_guard import LoginRoute, login_required
from app.interfaces.http.deps import get_services, require_superuser

router = APIRouter(prefix="/admin/packages", tags=["admin"], route_class=LoginRoute)


@router.get("")
@login_required
async def list_packages(
    agent_id: str | None = None,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> list[PackageSummary]:
    """列出技能包（可选项按 agent 过滤）。"""
    del account
    assert services.skill_packages is not None
    return await services.skill_packages.list_packages(agent_id)


@router.post("/{agent_id}/drafts")
@login_required
async def create_draft(
    agent_id: str,
    request: CreateDraftRequest,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> PackageDetail:
    """从标准模板创建草稿。"""
    assert services.skill_packages is not None
    return await services.skill_packages.create_draft(
        account_id=account.account_id,
        agent_id=agent_id,
        version=request.version,
        template_id=request.template_id,
        display_name=request.display_name,
    )


@router.get("/{package_id}")
@login_required
async def get_package(
    package_id: uuid.UUID,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> PackageDetail:
    """读取技能包详情（含可编辑文件）。"""
    del account
    assert services.skill_packages is not None
    return await services.skill_packages.get_package(package_id)


@router.put("/{package_id}/files")
@login_required
async def save_file(
    package_id: uuid.UUID,
    request: SaveFileRequest,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> PackageFile:
    """保存单个可编辑文件（新建或覆盖）。"""
    assert services.skill_packages is not None
    return await services.skill_packages.save_file(
        package_id,
        path=request.path,
        content=request.content,
        account_id=account.account_id,
    )


@router.delete("/{package_id}/files/{path:path}")
@login_required
async def delete_file(
    package_id: uuid.UUID,
    path: str,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> dict[str, bool]:
    """删除单个可编辑文件。"""
    assert services.skill_packages is not None
    await services.skill_packages.delete_file(package_id, path=path, account_id=account.account_id)
    return {"deleted": True}


@router.post("/{package_id}/validate")
@login_required
async def validate_package(
    package_id: uuid.UUID,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> ValidateResult:
    """静态校验草稿（不落库 / 不发布）。"""
    del account
    assert services.skill_packages is not None
    return await services.skill_packages.validate(package_id)


@router.post("/{package_id}/publish")
@login_required
async def publish_package(
    package_id: uuid.UUID,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> PublishedPackage:
    """发布草稿为当前生效版本。"""
    assert services.skill_packages is not None
    return await services.skill_packages.publish(package_id, account_id=account.account_id)


@router.post("/{agent_id}/rollback")
@login_required
async def rollback_package(
    agent_id: str,
    request: RollbackRequest,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> PublishedPackage:
    """回滚到指定已发布版本。"""
    assert services.skill_packages is not None
    return await services.skill_packages.rollback(
        agent_id, request.version, account_id=account.account_id
    )


@router.post("/{package_id}/debug/preview")
@login_required
async def debug_preview(
    package_id: uuid.UUID,
    request: DebugPreviewRequest,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> PreviewResult:
    """对草稿版本跑一次真实对话，返回正文 + RunEvent trace。"""
    return await run_draft_preview(
        services, package_id, user_input=request.user_input, account_id=account.account_id
    )


@router.post("/{package_id}/debug/tool")
@login_required
async def debug_tool(
    package_id: uuid.UUID,
    request: ToolSmokeRequest,
    account: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> ToolSmokeResult:
    """对草稿版本的工具执行一次真实调用（脚本 / MCP / 元工具）。"""
    del account
    return await run_tool_smoke(
        services,
        package_id,
        tool_name=request.tool_name,
        arguments=request.arguments,
    )


__all__ = ["router"]
