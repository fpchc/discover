"""技能包 bundle 纯函数单测（无网络 / 无 DB）。"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

from app.application.skill_package import bundle
from app.application.skill_package.service import SkillPackageService
from app.config.loader import load_mcp_servers
from app.config.settings import Settings
from app.harness.skill.loader import AgentLoader
from app.infrastructure.database.models import AgentPackageEntryRecord

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_zip_dir_unzip_to_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(source / "AGENT.md", "# agent\n")
    _write(source / "skill" / "SKILL.md", "# skill\n")
    _write(source / "skill" / "scripts" / "run.py", "print(1)\n")
    data = bundle.zip_dir(source)

    target = tmp_path / "target"
    bundle.unzip_to(data, target)

    assert (target / "AGENT.md").read_text(encoding="utf-8") == "# agent\n"
    assert (target / "skill" / "SKILL.md").read_text(encoding="utf-8") == "# skill\n"
    assert (target / "skill" / "scripts" / "run.py").read_text(encoding="utf-8") == "print(1)\n"


def test_unzip_to_rejects_traversal(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil.txt", "boom")
    target = tmp_path / "target"

    try:
        bundle.unzip_to(buffer.getvalue(), target)
    except ValueError as exc:
        assert "越界" in str(exc)
    else:
        raise AssertionError("未拒绝 zip-slip 路径穿越")

    assert not (tmp_path / "evil.txt").exists()


def test_read_editable_files_excludes_scripts_and_schemas(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _write(agent_dir / "AGENT.md", "agent")
    _write(agent_dir / "skill" / "SKILL.md", "skill")
    _write(agent_dir / "skill" / "references" / "guide.md", "ref")
    _write(agent_dir / "skill" / "templates" / "tpl.html", "tpl")
    _write(agent_dir / "skill" / "scripts" / "calc.py", "code")
    _write(agent_dir / "skill" / "schemas" / "input.json", "{}")

    files = bundle.read_editable_files(agent_dir)

    assert files == {
        "AGENT.md": "agent",
        "skill/SKILL.md": "skill",
        "skill/references/guide.md": "ref",
        "skill/templates/tpl.html": "tpl",
    }


def test_write_overlay_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    try:
        bundle.write_overlay(root, {"../evil.md": "x"})
    except ValueError as exc:
        assert "非法文件路径" in str(exc)
    else:
        raise AssertionError("未拒绝 overlay 路径穿越")

    assert not (tmp_path / "evil.md").exists()


def test_write_bundle_marker_round_trip(tmp_path: Path) -> None:
    marker = tmp_path / "agent" / "v1" / bundle.BUNDLE_MARKER
    bundle.write_bundle_marker(marker, "abc123")

    assert bundle.read_bundle_marker(marker, "abc123") is True
    assert bundle.read_bundle_marker(marker, "other") is False


async def test_standard_template_renders_to_valid_package(tmp_path: Path) -> None:
    template_dir = ROOT / "agent_package_templates" / "standard"
    rendered = {
        path: SkillPackageService._render_template(
            content,
            agent_id="demo-agent",
            version="1.0.0",
            display_name="演示智能体",
        )
        for path, content in bundle.read_package_files(template_dir).items()
    }
    package_dir = tmp_path / "demo-agent"
    bundle.write_overlay(package_dir, rendered)

    registry = await load_mcp_servers(ROOT / "config" / "mcp-servers.yaml")
    loader = AgentLoader(Settings(_env_file=None), registry)
    package = await loader.load_package_dir(package_dir)

    assert package.manifest.agent_id == "demo-agent"
    assert package.manifest.display_name == "演示智能体"
    assert sorted(package.skills) == ["example-skill"]
    assert package.skill_failures == []


def test_entry_tree_materializes_nested_file_paths() -> None:
    package_id = uuid.uuid4()
    rows = [
        AgentPackageEntryRecord(
            id=1,
            package_id=package_id,
            parent_id=None,
            entry_type="directory",
            name="",
            content=None,
        ),
        AgentPackageEntryRecord(
            id=2,
            package_id=package_id,
            parent_id=1,
            entry_type="directory",
            name="client-finder",
            content=None,
        ),
        AgentPackageEntryRecord(
            id=3,
            package_id=package_id,
            parent_id=2,
            entry_type="directory",
            name="references",
            content=None,
        ),
        AgentPackageEntryRecord(
            id=4,
            package_id=package_id,
            parent_id=3,
            entry_type="file",
            name="architecture.md",
            content="tree",
        ),
    ]

    assert SkillPackageService._entries_to_file_map(rows) == {
        "client-finder/references/architecture.md": "tree"
    }
