"""技能包管理服务：草稿编辑、校验、发布、回滚、物化。

存储模型：草稿由独立标准模板初始化，完整包文件以 path + content 行存入
agent_package_entries；目录层级由 path 确定性投影，发布时直接从草稿文件构建
bundle，不再复制或叠加代码仓库中的现有 Agent。一次发布产出一个 agent 级
zip bundle（Blob 原子对象），DB 记录版本 / 状态 / checksum / 归属账号。
"""

from __future__ import annotations

import hashlib
import json
import re
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
    read_bundle_marker,
    read_package_files,
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
from app.infrastructure.database.models import AgentPackageEntryRecord, AgentPackageRecord
from app.shared.errors.base import BadRequestError, NotFoundError, RegistryValidationError

_CODE_DIRS: frozenset[str] = frozenset({"scripts", "schemas"})
_ENTRY_DIRECTORY = "directory"
_ENTRY_FILE = "file"


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
        self._db = db
        self._storage = storage
        self._loader = loader
        self._template_root = settings.agent_package_template_dir.resolve()
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
                        select(AgentPackageEntryRecord).where(
                            AgentPackageEntryRecord.package_id == package_id
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
        """下载 bundle 并物化为可加载的 agent 目录（幂等：校验和一致复用）。"""
        package_root = (
            self._bundle_dir / "_published" / package.agent_id / package.version
        ).resolve()
        target = (package_root / package.agent_id).resolve()
        self._ensure_within_bundle_dir(target)
        marker = target / BUNDLE_MARKER
        if await anyio.to_thread.run_sync(read_bundle_marker, marker, package.checksum):
            return target
        data = await self._storage.load_once(package.storage_key)
        await anyio.to_thread.run_sync(unzip_to, data, target)
        await anyio.to_thread.run_sync(write_bundle_marker, marker, package.checksum)
        return target

    async def load_draft_package(self, package_id: uuid.UUID) -> AgentPackage:
        """从草稿的完整文件集合物化并加载智能体包。"""
        package = await self._get_package_record(package_id)
        files = await self._load_file_map(package_id)
        workdir = self._bundle_dir / "_draft" / str(package_id) / package.agent_id
        await anyio.to_thread.run_sync(shutil.rmtree, workdir, True)
        await anyio.to_thread.run_sync(write_overlay, workdir, files)
        return await self._loader.load_package_dir(workdir)

    # ---- 草稿编辑 ----
    async def create_draft(
        self,
        *,
        account_id: str,
        agent_id: str,
        version: str,
        template_id: str = "standard",
        display_name: str | None = None,
    ) -> PackageDetail:
        """从标准模板创建草稿，不再复制现有代码仓库中的技能包。"""
        self._validate_agent_id(agent_id)
        self._validate_version(version)
        template_dir = self._template_dir(template_id)
        template_files = await anyio.to_thread.run_sync(read_package_files, template_dir)
        resolved_display_name = (
            display_name.strip() if display_name is not None and display_name.strip() else agent_id
        )
        files = {
            path: self._render_template(
                content,
                agent_id=agent_id,
                version=version,
                display_name=resolved_display_name,
            )
            for path, content in template_files.items()
        }
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
            await self._create_entry_tree(session, row.package_id, files)
            await session.commit()
        return await self.get_package(row.package_id)

    async def save_file(
        self, package_id: uuid.UUID, *, path: str, content: str, account_id: str
    ) -> PackageFile:
        """保存单个可编辑文件（新建或覆盖目录树叶子）。"""
        self._validate_file_path(path)
        async with self._db.session_factory() as session:
            row = await self._require_package(session, package_id)
            await self._upsert_file_entry(session, package_id, path, content)
            row.updated_by = account_id
            row.updated_at = local_now()
            await session.commit()
        return PackageFile(path=path, content=content)

    async def delete_file(self, package_id: uuid.UUID, *, path: str, account_id: str) -> None:
        """删除单个可编辑文件，并清理因此变为空目录的祖先节点。"""
        self._validate_file_path(path)
        async with self._db.session_factory() as session:
            row = await self._require_package(session, package_id)
            if await self._delete_file_entry(session, package_id, path):
                row.updated_by = account_id
                row.updated_at = local_now()
                await session.commit()

    # ---- 校验 / 发布 / 回滚 ----
    async def validate(self, package_id: uuid.UUID) -> ValidateResult:
        """使用草稿的完整文件集合执行静态校验。"""
        package = await self._get_package_record(package_id)
        files = await self._load_file_map(package_id)
        errors = await self._validate_files(package.agent_id, files)
        return ValidateResult(ok=not errors, errors=errors)

    async def publish(self, package_id: uuid.UUID, *, account_id: str) -> PublishedPackage:
        """校验并直接从草稿文件构建 bundle，不叠加代码仓库中的旧技能包。"""
        package = await self._get_package_record(package_id)
        files = await self._load_file_map(package_id)
        errors = await self._validate_files(package.agent_id, files)
        if errors:
            raise RegistryValidationError("发布失败，技能包校验未通过：" + "; ".join(errors))
        data = await self._build_bundle(package.agent_id, files)
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
    async def _get_package_record(self, package_id: uuid.UUID) -> AgentPackageRecord:
        async with self._db.session_factory() as session:
            return await self._require_package(session, package_id)

    async def _load_file_map(self, package_id: uuid.UUID) -> dict[str, str]:
        async with self._db.session_factory() as session:
            rows = await self._load_entry_rows(session, package_id)
        return self._entries_to_file_map(rows)

    async def _create_entry_tree(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
        files: dict[str, str],
    ) -> None:
        root = await self._ensure_root(session, package_id)
        directories: dict[str, AgentPackageEntryRecord] = {"": root}
        for path, content in sorted(files.items()):
            parts = Path(path).parts
            parent = root
            directory_path = ""
            for name in parts[:-1]:
                directory_path = f"{directory_path}/{name}".strip("/")
                directory = directories.get(directory_path)
                if directory is None:
                    directory = AgentPackageEntryRecord(
                        package_id=package_id,
                        parent_id=parent.id,
                        entry_type=_ENTRY_DIRECTORY,
                        name=name,
                        content=None,
                    )
                    session.add(directory)
                    await session.flush()
                    directories[directory_path] = directory
                parent = directory
            session.add(
                AgentPackageEntryRecord(
                    package_id=package_id,
                    parent_id=parent.id,
                    entry_type=_ENTRY_FILE,
                    name=parts[-1],
                    content=content,
                )
            )

    async def _upsert_file_entry(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
        path: str,
        content: str,
    ) -> None:
        root = await self._ensure_root(session, package_id)
        rows = await self._load_entry_rows(session, package_id)
        nodes = {(row.parent_id, row.name): row for row in rows}
        parent = root
        directory_path = ""
        for name in Path(path).parts[:-1]:
            directory_path = f"{directory_path}/{name}".strip("/")
            node = nodes.get((parent.id, name))
            if node is None:
                node = AgentPackageEntryRecord(
                    package_id=package_id,
                    parent_id=parent.id,
                    entry_type=_ENTRY_DIRECTORY,
                    name=name,
                    content=None,
                )
                session.add(node)
                await session.flush()
                nodes[(parent.id, name)] = node
            elif node.entry_type != _ENTRY_DIRECTORY:
                raise BadRequestError(f"路径冲突：{directory_path}")
            parent = node
        name = Path(path).parts[-1]
        node = nodes.get((parent.id, name))
        if node is None:
            session.add(
                AgentPackageEntryRecord(
                    package_id=package_id,
                    parent_id=parent.id,
                    entry_type=_ENTRY_FILE,
                    name=name,
                    content=content,
                )
            )
        elif node.entry_type == _ENTRY_FILE:
            node.content = content
        else:
            raise BadRequestError(f"路径冲突：{path}")

    async def _delete_file_entry(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
        path: str,
    ) -> bool:
        rows = await self._load_entry_rows(session, package_id)
        files = self._entries_to_file_map(rows)
        if path not in files:
            return False
        rows_by_id = {row.id: row for row in rows}
        target = next(row for row in rows if self._entry_path(row, rows_by_id) == path)
        current_parent_id = target.parent_id
        await session.delete(target)
        deleted_ids = {target.id}
        while current_parent_id is not None:
            parent = rows_by_id[current_parent_id]
            has_other_child = any(
                row.parent_id == parent.id and row.id not in deleted_ids for row in rows
            )
            if has_other_child:
                break
            await session.delete(parent)
            deleted_ids.add(parent.id)
            current_parent_id = parent.parent_id
        return True

    async def _ensure_root(
        self,
        session: AsyncSession,
        package_id: uuid.UUID,
    ) -> AgentPackageEntryRecord:
        row = (
            (
                await session.execute(
                    select(AgentPackageEntryRecord).where(
                        AgentPackageEntryRecord.package_id == package_id,
                        AgentPackageEntryRecord.parent_id.is_(None),
                        AgentPackageEntryRecord.entry_type == _ENTRY_DIRECTORY,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
        row = AgentPackageEntryRecord(
            package_id=package_id,
            parent_id=None,
            entry_type=_ENTRY_DIRECTORY,
            name="",
            content=None,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def _load_entry_rows(
        session: AsyncSession,
        package_id: uuid.UUID,
    ) -> list[AgentPackageEntryRecord]:
        return list(
            (
                await session.execute(
                    select(AgentPackageEntryRecord).where(
                        AgentPackageEntryRecord.package_id == package_id
                    )
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _entries_to_file_map(rows: Sequence[AgentPackageEntryRecord]) -> dict[str, str]:
        by_id = {row.id: row for row in rows}

        def resolve(row: AgentPackageEntryRecord) -> str:
            if row.parent_id is None:
                return row.name
            parent = by_id.get(row.parent_id)
            if parent is None:
                raise RegistryValidationError(f"技能包目录树损坏：缺少父节点 {row.parent_id}")
            parent_path = resolve(parent)
            return f"{parent_path}/{row.name}".strip("/")

        return {resolve(row): row.content or "" for row in rows if row.entry_type == _ENTRY_FILE}

    @staticmethod
    def _entry_path(
        row: AgentPackageEntryRecord,
        rows_by_id: dict[int, AgentPackageEntryRecord],
    ) -> str:
        segments = [row.name]
        parent_id = row.parent_id
        while parent_id is not None:
            parent = rows_by_id[parent_id]
            if parent.parent_id is None:
                break
            segments.append(parent.name)
            parent_id = parent.parent_id
        return "/".join(reversed(segments))

    async def _validate_files(self, agent_id: str, files: dict[str, str]) -> list[str]:
        workdir = self._bundle_dir / "_draft" / uuid.uuid4().hex / agent_id
        try:
            await anyio.to_thread.run_sync(write_overlay, workdir, files)
            await self._loader.load_package_dir(workdir)
        except (RegistryValidationError, ValueError, OSError) as exc:
            return [str(exc)]
        finally:
            await anyio.to_thread.run_sync(shutil.rmtree, workdir.parent, True)
        return []

    async def _build_bundle(self, agent_id: str, files: dict[str, str]) -> bytes:
        workdir = self._bundle_dir / "_build" / uuid.uuid4().hex / agent_id
        try:
            await anyio.to_thread.run_sync(write_overlay, workdir, files)
            data = await anyio.to_thread.run_sync(zip_dir, workdir)
        finally:
            await anyio.to_thread.run_sync(shutil.rmtree, workdir.parent, True)
        if len(data) > self._max_bytes:
            raise RegistryValidationError(f"技能包 bundle 超过大小上限（{self._max_bytes} 字节）")
        return data

    def _template_dir(self, template_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", template_id):
            raise BadRequestError(f"非法模板 ID：{template_id}")
        candidate = (self._template_root / template_id).resolve()
        if not candidate.is_relative_to(self._template_root) or not candidate.is_dir():
            raise BadRequestError(f"技能包模板不存在：{template_id}")
        return candidate

    @staticmethod
    def _render_template(content: str, *, agent_id: str, version: str, display_name: str) -> str:
        replacements = {
            "agent_id": agent_id,
            "version": json.dumps(version, ensure_ascii=False),
            "display_name": json.dumps(display_name, ensure_ascii=False),
        }
        rendered = content
        for key, value in replacements.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        if re.search(r"\{\{[a-z_]+\}\}", rendered):
            raise RegistryValidationError("标准模板包含未解析的占位符")
        return rendered

    @staticmethod
    def _validate_agent_id(agent_id: str) -> None:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", agent_id):
            raise BadRequestError("agent_id 必须为 kebab-case")
        if agent_id == "generic":
            raise BadRequestError("agent_id 不能使用保留字 generic")

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
        row: AgentPackageRecord, file_rows: Sequence[AgentPackageEntryRecord]
    ) -> PackageDetail:
        files = [
            PackageFile(path=path, content=content)
            for path, content in sorted(SkillPackageService._entries_to_file_map(file_rows).items())
        ]

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
