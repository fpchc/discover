"""智能体工作区（L1）：创建 / 隔离 / 清理。

隔离维度 = 账号 + 会话 + 运行实例（P0 边界收紧）：可写根目录按
`workspaces/{account_id}/{conversation_id}/{run_id}` 隔离，避免跨账号泄漏、
同会话并发覆盖与产物归属错误。agent_id 只用于校验与记录，不进入可写路径。
路径一律由通过格式校验的标识拼接而成，杜绝穿越；重文件操作
（mkdir / rmtree）走 anyio 线程池，避免阻塞事件循环。
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import anyio

from app.config.settings import Settings
from app.shared.errors.base import SessionError

_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True)
class Workspace:
    """智能体的可写目录句柄（纯内部运行句柄）。"""

    # pragma: 简化 — 内部运行句柄，不跨边界，无需 pydantic
    agent_id: str
    root: Path
    account_id: str = ""
    conversation_id: str = ""
    run_id: str = ""


def _validate_id(value: str, *, label: str) -> None:
    """标识格式校验（kebab-case），从根上杜绝路径穿越。"""
    if not _ID_PATTERN.fullmatch(value):
        raise SessionError(f"非法{label}：{value!r}（仅允许小写字母数字与连字符）")


def _is_within(parent: Path, child: Path) -> bool:
    """child 解析后是否落在 parent 内（防符号链接逃逸）。"""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _mkdir_workspace(root: Path, account_id: str, conversation_id: str, run_id: str) -> Path:
    path = root / account_id / conversation_id / run_id
    _mkdir(path)
    return path


def _rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


class WorkspaceManager:
    """工作区管理器：创建 / 清理智能体工作区（按 agent 键控）。"""

    def __init__(self, settings: Settings) -> None:
        self._root_setting = settings.agent_workspace_root_dir

    async def create(
        self,
        agent_id: str,
        *,
        account_id: str,
        conversation_id: str,
        run_id: str,
    ) -> Workspace:
        """创建（或复用）运行级工作区并返回句柄。"""
        _validate_id(agent_id, label="智能体标识")
        _validate_id(account_id, label="账号标识")
        _validate_id(conversation_id, label="会话标识")
        _validate_id(run_id, label="运行标识")
        root = self._root_setting.resolve()
        path = await anyio.to_thread.run_sync(
            _mkdir_workspace, root, account_id, conversation_id, run_id
        )
        if not _is_within(root, path):
            raise SessionError("智能体工作区越出工作区根目录，已拒绝")
        return Workspace(
            agent_id=agent_id,
            root=path,
            account_id=account_id,
            conversation_id=conversation_id,
            run_id=run_id,
        )

    def workspace_path(self, account_id: str, conversation_id: str, run_id: str) -> Path:
        """工作区路径计算（不创建目录）。标识格式校验保证路径合法。"""
        _validate_id(account_id, label="账号标识")
        _validate_id(conversation_id, label="会话标识")
        _validate_id(run_id, label="运行标识")
        return self._root_setting / account_id / conversation_id / run_id

    async def remove(self, workspace: Workspace) -> None:
        """删除单个工作区。越界路径一律拒绝。"""
        if not _is_within(self._root_setting, workspace.root):
            raise SessionError("拒绝删除工作区根目录之外的路径")
        await anyio.to_thread.run_sync(_rmtree, workspace.root)
