"""技能包 bundle 打包 / 解包 / 物化辅助（纯同步函数，I/O 由调用方走线程池）。

bundle = 一个智能体包的完整目录（AGENT.md + 各技能 SKILL.md/references/schemas/
scripts/templates）打成的 zip 字节流；一次发布一个 bundle，Blob 原子替换。

可编辑面只包含 AGENT.md / SKILL.md / references / templates；scripts 与
schemas 属代码发布，管理员不直接编辑（发布时从代码包原样拷入 bundle）。
"""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

# 代码发布、不可在线编辑的目录（脚本与入参约束）
_CODE_DIRS: frozenset[str] = frozenset({"scripts", "schemas"})

# 物化缓存命中标记文件名
BUNDLE_MARKER = ".bundle_checksum"


def _relative_files(root: Path) -> list[Path]:
    """目录下全部普通文件（排除 __pycache__ 与 pyc）。"""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def zip_dir(root: Path) -> bytes:
    """把目录打成 zip 字节流（相对路径存储）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _relative_files(root):
            archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()


def unzip_to(data: bytes, target: Path) -> None:
    """解包到目标目录，拒绝 zip-slip 路径穿越。"""
    target.resolve().mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            info = archive.getinfo(name)
            destination = (target / name).resolve()
            if not destination.is_relative_to(root):
                raise ValueError(f"bundle 包含越界路径：{name}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out)


def copy_tree(source: Path, target: Path) -> None:
    """复制目录树（排除编译产物），目标已存在时先清空。"""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def write_overlay(root: Path, files: dict[str, str]) -> None:
    """把可编辑文件按相对路径写回物化目录；拒绝越界路径。"""
    base = root.resolve()
    for rel, content in files.items():
        destination = (root / rel).resolve()
        if not destination.is_relative_to(base):
            raise ValueError(f"非法文件路径：{rel}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def read_package_files(package_dir: Path) -> dict[str, str]:
    """读取包目录中的全部普通文件（排除 Python 编译产物）。"""
    if not package_dir.is_dir():
        raise ValueError(f"技能包模板不存在：{package_dir}")
    files: dict[str, str] = {}
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files[path.relative_to(package_dir).as_posix()] = path.read_text(
            encoding="utf-8", errors="replace"
        )
    return files


def read_editable_files(agent_dir: Path) -> dict[str, str]:
    """读取可由管理员编辑的文件（AGENT/SKILL/references/templates）。"""
    return {
        path: content
        for path, content in read_package_files(agent_dir).items()
        if not any(part in _CODE_DIRS for part in Path(path).parts)
    }


def read_bundle_marker(marker: Path, checksum: str) -> bool:
    """物化缓存命中判断：标记内容与发布校验和一致即复用。"""
    return marker.is_file() and marker.read_text(encoding="utf-8").strip() == checksum


def write_bundle_marker(marker: Path, checksum: str) -> None:
    """写入物化缓存标记。"""
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(checksum, encoding="utf-8")


__all__ = [
    "BUNDLE_MARKER",
    "copy_tree",
    "read_bundle_marker",
    "read_editable_files",
    "read_package_files",
    "unzip_to",
    "write_bundle_marker",
    "write_overlay",
    "zip_dir",
]
