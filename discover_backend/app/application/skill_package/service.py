"""技能包管理服务：草稿编辑、校验、发布、回滚、物化。

存储模型：可编辑面（AGENT.md / SKILL.md / references / templates）以文件行
存库（agent_package_files）；scripts 与 schemas 仍由代码发布，发布时从代码包
拷入 bundle。一次发布产出**一个 agent 级 zip bundle**（Blob 原子对象），
DB 记录版本 / 状态 / checksum / 归属账号。
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.skill_packages import (
    PackageDetail,
    PackageFile,
    PackageStatus,
    PackageSummary,
    PublishedPackage,
    ValidateResult,
)
from app.application.skill_package.bundle import (
    BUNDLE_MARKER,
    copy_tree,
    read_bundle_marker,
    read_editable_files,
    unzip_to,
    write_bundle_marker,
    write_overlay,
    zip_dir,
)
from app.config.settings import Settings
from app.environment.storage.base import BaseStorage
from app.harness.skill.definition import AgentPackage
from app.harness.skill.loader import AgentLoader
from app.infrastructure.database.base import local_now
from app.infrastructure.database.engine import Database
from app.infrastructure.database.models import AgentPackageFileRecord, AgentPackageRecord
from app.shared.errors.base import BadRequestError, NotFoundError, RegistryValidationError

_CODE_DIRS: frozenset[str] = frozenset({"scripts", "schemas"})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SkillPackageService:
    """管理员技能包管理用例：只做编排与持久化，不感知 HTTP 帧。"""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        storage: BaseStorage,
        loader: AgentLoader,
    ) -> None:
        self._settings = settings
        self._db = db
        self._storage = storage
        self._loader = loader
        self._agents_root = settings.agents_root_dir.resolve()
        self._bundle_dir = settings.agent_package_bundle_dir
        self._max_bytes = settings.agent_package_bundle_max_bytes

    # ---- 只读查询 ----
    async def list_packages(self, agent_id: str | None = None) -> list[PackageSummary]:
        """列出技能包（默认全量，可按 agent 过滤）。"""
        async with self._db.session_factory() as session:
            statement = select(AgentPackageRecord).order_by(AgentPackageRecord.updated_at.desc())
            if agent_id is not None:
                statement = statement.where(AgentPackageRecord.agent_id == agent_id)
            rows = (await session.execute(statement)).scalars().all()
        return [self._summary(row) for row in rows]

    async def get_package(self, package_id: uuid.UUID) -> PackageDetail:
        """读取技能包详情（含可编辑文件全集）。"""
        async with self._db.session_factory() as session:
            row = await session.get(AgentPackageRecord, package_id)
            if row is None:
                raise NotFoundError(f"技能包不存在：{package_id}")
            file_rows = (
                (
                    await session.execute(
                        select(AgentPackageFileRecord).where(
                            AgentPackageFileRecord.package_id == package_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        return self._detail(row, file_rows)

    async def list_published(self) -> list[PublishedPackage]:
        """当前生效的已发布技能包（DatabasePackageSource 加载来源）。"""
        async with self._db.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AgentPackageRecord).where(
                            AgentPackageRecord.status == PackageStatus.PUBLISHED.value,
                            AgentPackageRecord.enabled.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [self._published(row) for row in rows]

    async def materialize(self, package: PublishedPackage) -> Path:
        """下载 bundle 并物化到本地缓存目录（幂等：校验和一致复用）。"""
        target = (self._bundle_dir / package.agent_id / package.version).resolve()
        self._ensure_within_bundle_dir(target)
        marker = target / BUNDLE_MARKER
        if await anyio.to_thread.run_sync(read_bundle_marker, marker, package.checksum):
            return target
        data = await self._storage.load_once(package.storage_key)
        await anyio.to_thread.run_sync(unzip_to, data, target)
        await anyio.to_thread.run_sync(write_bundle_marker, marker, package.checksum)
        return target

    async def load_draft_package(self, package_id: uuid.UUID) -> AgentPackage:
        """把草稿物化为可加载的智能体包（代码包脚本 + 草稿编辑面合并）。"""
        detail = await self.get_package(package_id)
        files = {item.path: item.content for item in detail.files}
        workdir = self._bundle_dir / "_draft" / str(package_id)
        await anyio.to_thread.run_sync(copy_tree, self._agent_dir(detail.agent_id), workdir)
        await anyio.to_thread.run_sync(write_overlay, workdir, files)
        return await self._loader.load_package_dir(workdir)

    # ---- 草稿编辑 ----
    async def create_draft(self, *, account_id: str, agent_id: str, version: str) -> PackageDetail:
        """从代码包种子创建草稿：可编辑文件来自 agents/{agent}（不含脚本/schema）。"""
        agent_dir = self._agent_dir(agent_id)
        self._validate_version(version)
        editable = await anyio.to_thread.run_sync(read_editable_files, agent_dir)
        now = local_now()
        row = AgentPackageRecord(
            agent_id=agent_id,
            version=version,
            status=PackageStatus.DRAFT.value,
            enabled=False,
            created_by=account_id,
            updated_by=account_id,
            created_at=now,
            updated_at=now,
        )
        async with self._db.session_factory() as session:
            session.add(row)
            await session.flush()
            for path, content in editable.items():
                session.add(
                    AgentPackageFileRecord(package_id=row.package_id, path=path, content=content)
                )
            await session.commit()
        return await self.get_package(row.package_id)

    async def save_file(
        self, package_id: uuid.UUID, *, path: str, content: str, account_id: str
    ) -> PackageFile:
        """保存单个可编辑文件（新建或覆盖）。"""
        self._validate_file_path(path)
        async with self._db.session_factory() as session:
            row = await self._require_package(session, package_id)
            file_row = (
                (
                    await session.execute(
                        select(AgentPackageFileRecord).where(
                            AgentPackageFileRecord.package_id == package_id,
                            AgentPackageFileRecord.path == path,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if file_row is None:
                file_row = AgentPackageFileRecord(package_id=package_id, path=path, content=content)
                session.add(file_row)
            else:
                file_row.content = content
            row.updated_by = account_id
            row.updated_at = local_now()
            await session.commit()
        return PackageFile(path=path, content=content)

    async def delete_file(self, package_id: uuid.UUID, *, path: str, account_id: str) -> None:
        """删除单个可编辑文件。"""
        async with self._db.session_factory() as session:
            row = await self._require_package(session, package_id)
            file_row = (
                (
                    await session.execute(
                        select(AgentPackageFileRecord).where(
                            AgentPackageFileRecord.package_id == package_id,
                            AgentPackageFileRecord.path == path,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if file_row is not None:
                await session.delete(file_row)
                row.updated_by = account_id
                row.updated_at = local_now()
                await session.commit()

    # ---- 校验 / 发布 / 回滚 ----
    async def validate(self, package_id: uuid.UUID) -> ValidateResult:
        """静态校验草稿：代码包脚本 + 草稿可编辑文件合并后走 AgentLoader。"""
        detail = await self.get_package(package_id)
        files = {item.path: item.content for item in detail.files}
        errors = await self._validate_files(detail.agent_id, files)
        return ValidateResult(ok=not errors, errors=errors)

    async def publish(self, package_id: uuid.UUID, *, account_id: str) -> PublishedPackage:
        """发布草稿：校验通过后打包上传，置为当前生效版本（其余已发布停用）。"""
        detail = await self.get_package(package_id)
        files = {item.path: item.content for item in detail.files}
        errors = await self._validate_files(detail.agent_id, files)
        if errors:
            raise RegistryValidationError("发布失败，技能包校验未通过：" + "; ".join(errors))
        data = await self._build_bundle(detail.agent_id, files)
        checksum = _sha256(data)
        storage_key = f"{uuid.uuid4().hex}.zip"
        await self._storage.save(storage_key, data)
        async with self._db.session_factory() as session:
            row = await self._require_package(session, package_id)
            await self._disable_published(session, row.agent_id, exclude=package_id)
            row.status = PackageStatus.PUBLISHED.value
            row.enabled = True
            row.storage_key = storage_key
            row.checksum = checksum
            row.published_at = local_now()
            row.updated_by = account_id
            row.updated_at = local_now()
            await session.commit()
        return PublishedPackage(
            agent_id=row.agent_id,
            version=row.version,
            storage_key=storage_key,
            checksum=checksum,
        )

    async def rollback(self, agent_id: str, version: str, *, account_id: str) -> PublishedPackage:
        """回滚到指定已发布版本（该版本重新置为生效）。"""
        async with self._db.session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(AgentPackageRecord).where(
                            AgentPackageRecord.agent_id == agent_id,
                            AgentPackageRecord.version == version,
                            AgentPackageRecord.status == PackageStatus.PUBLISHED.value,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                raise NotFoundError(f"未找到已发布版本：{agent_id}@{version}")
            await self._disable_published(session, agent_id, exclude=row.package_id)
            row.enabled = True
            row.updated_by = account_id
            row.updated_at = local_now()
            await session.commit()
            return self._published(row)

    # ---- 内部工具 ----
    def _agent_dir(self, agent_id: str) -> Path:
        agent_dir = self._agents_root / agent_id
        if not agent_dir.is_dir():
            raise NotFoundError(f"未知智能体：{agent_id}")
        return agent_dir

    async def _validate_files(self, agent_id: str, files: dict[str, str]) -> list[str]:
        workdir = self._bundle_dir / "_draft" / uuid.uuid4().hex
        try:
            await anyio.to_thread.run_sync(copy_tree, self._agent_dir(agent_id), workdir)
            await anyio.to_thread.run_sync(write_overlay, workdir, files)
            await self._loader.load_package_dir(workdir)
        except (RegistryValidationError, ValueError, OSError) as exc:
            return [str(exc)]
        finally:
            await anyio.to_thread.run_sync(shutil.rmtree, workdir, True)
        return []

    async def _build_bundle(self, agent_id: str, files: dict[str, str]) -> bytes:
        workdir = self._bundle_dir / "_build" / uuid.uuid4().hex
        try:
            await anyio.to_thread.run_sync(copy_tree, self._agent_dir(agent_id), workdir)
            await anyio.to_thread.run_sync(write_overlay, workdir, files)
            data = await anyio.to_thread.run_sync(zip_dir, workdir)
        finally:
            await anyio.to_thread.run_sync(shutil.rmtree, workdir, True)
        if len(data) > self._max_bytes:
            raise RegistryValidationError(f"技能包 bundle 超过大小上限（{self._max_bytes} 字节）")
        return data

    async def _require_package(
        self, session: AsyncSession, package_id: uuid.UUID
    ) -> AgentPackageRecord:
        row = await session.get(AgentPackageRecord, package_id)
        if row is None:
            raise NotFoundError(f"技能包不存在：{package_id}")
        return row

    async def _disable_published(
        self, session: AsyncSession, agent_id: str, *, exclude: uuid.UUID
    ) -> None:
        rows = (
            (
                await session.execute(
                    select(AgentPackageRecord).where(
                        AgentPackageRecord.agent_id == agent_id,
                        AgentPackageRecord.status == PackageStatus.PUBLISHED.value,
                        AgentPackageRecord.enabled.is_(True),
                        AgentPackageRecord.package_id != exclude,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.enabled = False

    @staticmethod
    def _validate_version(version: str) -> None:
        candidate = Path(version)
        if not version or version in {".", ".."} or candidate.name != version:
            raise BadRequestError(f"非法版本号：{version}")

    def _ensure_within_bundle_dir(self, target: Path) -> None:
        base = self._bundle_dir.resolve()
        if not target.is_relative_to(base):
            raise ValueError(f"非法物化路径：{target}")

    @staticmethod
    def _validate_file_path(path: str) -> None:
        if not path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise BadRequestError(f"非法文件路径：{path}")
        if any(part in _CODE_DIRS for part in Path(path).parts):
            raise BadRequestError("scripts 与 schemas 由代码发布，不支持在线编辑")

    @staticmethod
    def _summary(row: AgentPackageRecord) -> PackageSummary:
        return PackageSummary(
            package_id=str(row.package_id),
            agent_id=row.agent_id,
            version=row.version,
            status=PackageStatus(row.status),
            enabled=row.enabled,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _published(row: AgentPackageRecord) -> PublishedPackage:
        return PublishedPackage(
            agent_id=row.agent_id,
            version=row.version,
            storage_key=row.storage_key or "",
            checksum=row.checksum or "",
        )

    @staticmethod
    def _detail(
        row: AgentPackageRecord, file_rows: Sequence[AgentPackageFileRecord]
    ) -> PackageDetail:
        files = sorted(
            (PackageFile(path=item.path, content=item.content) for item in file_rows),
            key=lambda item: item.path,
        )
        return PackageDetail(
            package_id=str(row.package_id),
            agent_id=row.agent_id,
            version=row.version,
            status=PackageStatus(row.status),
            enabled=row.enabled,
            files=files,
            published_at=row.published_at,
            updated_at=row.updated_at,
        )


__all__ = ["SkillPackageService"]
