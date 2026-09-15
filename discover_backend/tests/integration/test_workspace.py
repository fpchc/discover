"""智能体工作区测试：按 agent 键控、跨会话共享、标识防穿越。"""

from pathlib import Path

import pytest
from app.config.settings import Settings
from app.environment.workspace.service import WorkspaceManager
from app.shared.errors.base import SessionError


def _manager(tmp_path: Path, **overrides: object) -> WorkspaceManager:
    return WorkspaceManager(
        Settings(_env_file=None, agent_workspace_root_dir=tmp_path, **overrides)
    )


async def test_workspace_run_level_isolation(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    ws1 = await manager.create(
        "finder", account_id="acct-1", conversation_id="conv-1", run_id="run-1"
    )
    ws2 = await manager.create(
        "finder", account_id="acct-1", conversation_id="conv-1", run_id="run-1"
    )
    assert ws1.root == ws2.root  # 同一运行复用工作区
    assert ws1.root.is_relative_to(tmp_path)
    ws_other_run = await manager.create(
        "finder", account_id="acct-1", conversation_id="conv-1", run_id="run-2"
    )
    assert ws_other_run.root != ws1.root  # 不同运行隔离
    ws_other_account = await manager.create(
        "finder", account_id="acct-2", conversation_id="conv-1", run_id="run-1"
    )
    assert ws_other_account.root != ws1.root  # 不同账号隔离


@pytest.mark.parametrize(
    "bad_id",
    ["../evil", "..", ".", "evil/../../", "Evil", "evil-", "-evil", "evil/x", ""],
)
async def test_workspace_rejects_traversal_ids(tmp_path: Path, bad_id: str) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(SessionError):
        await manager.create(
            "finder",
            account_id=bad_id,
            conversation_id="conv-1",
            run_id="run-1",
        )
