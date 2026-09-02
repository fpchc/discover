"""智能体包扫描与加载期校验（L2，agent-package-spec §8-§9）。

任一项失败该智能体或技能标记为无效并跳过，不影响其他智能体。
文件读写与目录扫描走 anyio 线程池，避免阻塞事件循环。
绝对路径禁令：脚本命中盘符前缀或根目录起始的路径字面量即判无效。
"""

from __future__ import annotations

import re
from pathlib import Path

import anyio
import yaml
from pydantic import ValidationError

from app.config.loader import MCPRegistry
from app.config.settings import Settings
from app.domain.assistant.models import GENERIC_ASSISTANT_ID
from app.domain.skill.definition import (
    AgentLoadFailure,
    AgentPackage,
    AgentRegistrySnapshot,
    SkillLoadResult,
)
from app.domain.skill.manifest import AgentManifest, SkillManifest
from app.shared.errors.base import ConfigError, RegistryValidationError

_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_DRIVE_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!/)")
_QUOTED_ROOT_PATTERN = re.compile(r"""['"][\\/][^'"\\n]+['"]""")


# ---- frontmatter 解析 ----
def _split_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    """拆分 YAML frontmatter 与正文。结构：---\\n<yaml>\\n---\\n<body>。"""
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        raise RegistryValidationError("清单必须以 --- 起始的 YAML frontmatter 开头")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise RegistryValidationError("清单 frontmatter 缺少结束 ---")
    header = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    try:
        parsed: object = yaml.safe_load(header)
    except yaml.YAMLError as exc:
        raise RegistryValidationError(f"清单 frontmatter 解析失败：{exc}") from exc
    if parsed is None:
        return {}, body
    if not isinstance(parsed, dict):
        raise RegistryValidationError("清单 frontmatter 顶层必须是映射")
    return {str(key): value for key, value in parsed.items()}, body


# ---- 路径与脚本扫描 ----
def _validate_rel_path(rel: str, *, kind: str) -> None:
    p = Path(rel)
    if not rel or p.is_absolute() or ".." in p.parts:
        raise RegistryValidationError(f"{kind}路径非法（须相对、无穿越）：{rel}")


def _resolve_existing(skill_dir: Path, rel: str) -> Path | None:
    """脚本 / 模板解析：仅技能目录（三级结构：agents/{agent}/{skill}）。"""
    candidate = skill_dir / Path(rel)
    if candidate.is_file():
        return candidate
    return None


def _require_file_within(root: Path, rel: str, *, subdir: str, kind: str) -> None:
    """文件须存在且位于 root/<subdir>/ 内（用于入参约束、门禁校验器）。"""
    _validate_rel_path(rel, kind=kind)
    candidate = root / rel
    if not candidate.is_file():
        raise RegistryValidationError(f"{kind}不存在：{rel}")
    base = (root / subdir).resolve()
    if not candidate.resolve().is_relative_to(base):
        raise RegistryValidationError(f"{kind}须位于 {subdir}/ 内：{rel}")


def _has_absolute_path_literal(text: str) -> bool:
    """启发式：盘符前缀（如 C:/）或带引号的根路径（"/data"、"\\share"）。"""
    return bool(_DRIVE_PATTERN.search(text) or _QUOTED_ROOT_PATTERN.search(text))


def _find_absolute_path_literals(scripts_dir: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(scripts_dir.rglob("*")):
        if not path.is_file():
            continue
        # 跳过 __pycache__ 编译产物：字节码内嵌 co_filename 绝对路径，按文本读
        # 会命中盘符模式，误判「脚本含绝对路径字面量」→ 本地跑过一次脚本即判技能无效。
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _has_absolute_path_literal(text):
            hits.append(str(path.relative_to(scripts_dir)))
    return hits


def _list_agent_dirs(agents_root: Path) -> list[Path]:
    if not agents_root.is_dir():
        raise ConfigError(f"智能体根目录不存在：{agents_root}")
    return sorted(p for p in agents_root.iterdir() if p.is_dir() and not p.name.startswith("."))


class AgentLoader:
    """智能体包加载器：扫描、解析、校验、脚本绝对路径字面量扫描。"""

    def __init__(self, settings: Settings, mcp_registry: MCPRegistry) -> None:
        self._settings = settings
        self._mcp_ids = {server.id for server in mcp_registry.servers}
        self._capability_ids = set(mcp_registry.capabilities)

    async def load_agents(self, agents_root: Path) -> AgentRegistrySnapshot:
        agent_dirs = await anyio.to_thread.run_sync(_list_agent_dirs, agents_root)
        packages: dict[str, AgentPackage] = {}
        failures: list[AgentLoadFailure] = []
        for agent_dir in agent_dirs:
            try:
                package = await self._load_package(agent_dir)
            except RegistryValidationError as exc:
                failures.append(AgentLoadFailure(agent_id=agent_dir.name, reason=str(exc)))
                continue
            packages[package.manifest.agent_id] = package
        return AgentRegistrySnapshot(packages=packages, failures=failures)

    async def _load_package(self, agent_dir: Path) -> AgentPackage:
        return await anyio.to_thread.run_sync(self._load_package_sync, agent_dir)

    def _load_package_sync(self, agent_dir: Path) -> AgentPackage:
        manifest = self._load_agent_manifest(agent_dir)
        skill_failures: list[SkillLoadResult] = []
        skills: dict[str, SkillManifest] = {}
        for skill_id in manifest.skills:
            skill_dir = agent_dir / skill_id
            try:
                skill = self._load_skill_manifest(skill_dir, skill_id)
            except RegistryValidationError as exc:
                skill_failures.append(
                    SkillLoadResult(skill_id=skill_id, ok=False, invalid_reason=str(exc))
                )
                continue
            skills[skill_id] = skill
        return AgentPackage(
            root=agent_dir,
            manifest=manifest,
            skills=skills,
            skill_failures=skill_failures,
        )

    def _load_agent_manifest(self, agent_dir: Path) -> AgentManifest:
        manifest_file = agent_dir / "AGENT.md"
        if not manifest_file.is_file():
            raise RegistryValidationError(f"缺少 AGENT.md：{agent_dir}")
        raw = manifest_file.read_text(encoding="utf-8")
        header, body = _split_frontmatter(raw)
        try:
            manifest = AgentManifest.model_validate(header)
        except ValidationError as exc:
            raise RegistryValidationError(f"AGENT.md 校验失败：{exc}") from exc
        manifest = manifest.model_copy(update={"body": body})
        self._validate_agent(manifest, agent_dir)
        return manifest

    def _validate_agent(self, manifest: AgentManifest, agent_dir: Path) -> None:
        if manifest.agent_id != agent_dir.name:
            raise RegistryValidationError(f"智能体 ID 必须等于目录名：{agent_dir.name}")
        if manifest.agent_id == GENERIC_ASSISTANT_ID:
            raise RegistryValidationError(f"智能体 ID 为保留字：{manifest.agent_id!r}")
        if not _ID_PATTERN.fullmatch(manifest.agent_id):
            raise RegistryValidationError(f"非法智能体 ID：{manifest.agent_id!r}")
        if not (manifest.scope.applies and manifest.scope.does_not_apply):
            raise RegistryValidationError("适用边界须同时写「适用」与「不适用」")
        if not manifest.skills:
            raise RegistryValidationError(f"技能索引为空：{manifest.agent_id}")
        if manifest.default_skill is not None and manifest.default_skill not in manifest.skills:
            raise RegistryValidationError("默认技能不在技能索引内")
        if len(manifest.body) > self._settings.agent_body_max_chars:
            raise RegistryValidationError(
                f"AGENT 正文超预算：{len(manifest.body)}/{self._settings.agent_body_max_chars} 字符"
            )

    def _load_skill_manifest(self, skill_dir: Path, skill_id: str) -> SkillManifest:
        manifest_file = skill_dir / "SKILL.md"
        if not manifest_file.is_file():
            raise RegistryValidationError(f"缺少 SKILL.md：{skill_dir}")
        raw = manifest_file.read_text(encoding="utf-8")
        header, body = _split_frontmatter(raw)
        try:
            manifest = SkillManifest.model_validate(header)
        except ValidationError as exc:
            raise RegistryValidationError(f"SKILL.md 校验失败（{skill_id}）：{exc}") from exc
        manifest = manifest.model_copy(update={"body": body})
        self._validate_skill(manifest, skill_dir)
        return manifest

    def _validate_skill(self, manifest: SkillManifest, skill_dir: Path) -> None:
        if manifest.skill_id != skill_dir.name:
            raise RegistryValidationError(f"技能 ID 必须等于目录名：{skill_dir.name}")
        if not _ID_PATTERN.fullmatch(manifest.skill_id):
            raise RegistryValidationError(f"非法技能 ID：{manifest.skill_id!r}")
        if not (manifest.scope.applies and manifest.scope.does_not_apply):
            raise RegistryValidationError("适用边界须同时写「适用」与「不适用」")
        if len(manifest.body) > self._settings.skill_body_max_chars:
            raise RegistryValidationError(
                f"SKILL 正文超预算：{len(manifest.body)}/{self._settings.skill_body_max_chars} 字符"
            )
        for dep in manifest.mcp_dependencies:
            if dep.server not in self._mcp_ids:
                raise RegistryValidationError(f"MCP 服务器未注册：{dep.server}")
        for cap_dep in manifest.capability_dependencies:
            if cap_dep.capability not in self._capability_ids:
                raise RegistryValidationError(f"平台能力未注册：{cap_dep.capability}")
        seen_names: set[str] = set()
        for script in manifest.scripts:
            if script.name in seen_names:
                raise RegistryValidationError(f"脚本工具名重复：{script.name}")
            seen_names.add(script.name)
            _validate_rel_path(script.path, kind="脚本")
            if _resolve_existing(skill_dir, script.path) is None:
                raise RegistryValidationError(f"脚本文件不存在：{script.path}")
            if script.schema_path is not None:
                _require_file_within(
                    skill_dir, script.schema_path, subdir="schemas", kind="入参约束文件"
                )
        for doc in manifest.documents:
            _validate_rel_path(doc.path, kind="参考文档")
            if not (skill_dir / doc.path).is_file():
                raise RegistryValidationError(f"参考文档不存在：{doc.path}")
        for template in manifest.templates:
            _validate_rel_path(template.path, kind="模板")
            if _resolve_existing(skill_dir, template.path) is None:
                raise RegistryValidationError(f"模板文件不存在：{template.path}")
        for gate in manifest.gates:
            if gate.validator is not None:
                _require_file_within(skill_dir, gate.validator, subdir="scripts", kind="门禁校验器")
            if gate.schema_path is not None:
                _require_file_within(
                    skill_dir, gate.schema_path, subdir="schemas", kind="门禁入参约束文件"
                )
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir():
            hits = _find_absolute_path_literals(scripts_dir)
            if hits:
                raise RegistryValidationError(f"脚本含绝对路径字面量：{hits[0]}")
