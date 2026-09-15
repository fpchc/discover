"""单元测试：断线续传 replay 路由（GET /chat-messages/{conversation_id}/runs/{run_id}）。

纯本地：伪 run_service.query + 伪 conversation_service.require_owned，无网络无 DB。
覆盖：正常返回快照摘要 + 事件；未知运行 / 跨账号 → 404。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.interfaces.http.chat import get_run_replay, resume_run
from app.shared.errors.base import NotFoundError

_RUN_ID = "run-1"
_CONVERSATION_ID = "conv-1"


def _result(
    *,
    account_id: str,
    status: str,
    reason: str | None,
    final_output: str,
    conversation_id: str = _CONVERSATION_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            identity=SimpleNamespace(account_id=account_id, conversation_id=conversation_id),
            termination=SimpleNamespace(
                status=SimpleNamespace(value=status),
                reason=SimpleNamespace(value=reason) if reason else None,
            ),
            output=SimpleNamespace(final_draft=final_output),
        ),
        events=[],
        last_seq=3,
    )


def _services(result: SimpleNamespace | None) -> SimpleNamespace:
    async def require_owned(account_id: str, conversation_id: str) -> None:
        del account_id, conversation_id

    async def query(run_id: str, *, after_seq: int = 0) -> SimpleNamespace | None:
        del run_id, after_seq
        return result

    return SimpleNamespace(
        conversation_service=SimpleNamespace(require_owned=require_owned),
        run_service=SimpleNamespace(query=query),
    )


async def test_replay_returns_snapshot_and_events() -> None:
    services = _services(
        _result(account_id="acct-1", status="succeeded", reason="completed", final_output="答案")
    )
    resp = await get_run_replay(
        conversation_id=_CONVERSATION_ID,
        run_id=_RUN_ID,
        account_id="acct-1",
        services=services,
    )
    assert resp.run_id == _RUN_ID
    assert resp.status == "succeeded"
    assert resp.reason == "completed"
    assert resp.final_output == "答案"
    assert resp.last_seq == 3


async def test_replay_unknown_run_returns_404() -> None:
    services = _services(None)
    with pytest.raises(NotFoundError):
        await get_run_replay(
            conversation_id=_CONVERSATION_ID,
            run_id=_RUN_ID,
            account_id="acct-1",
            services=services,
        )


async def test_replay_cross_account_returns_404() -> None:
    services = _services(
        _result(account_id="acct-2", status="succeeded", reason="completed", final_output="答案")
    )
    with pytest.raises(NotFoundError):
        await get_run_replay(
            conversation_id=_CONVERSATION_ID,
            run_id=_RUN_ID,
            account_id="acct-1",
            services=services,
        )


async def test_replay_wrong_conversation_returns_404() -> None:
    """run_id 属于另一个会话（同账号）→ 404，不跨会话泄露运行数据。"""
    services = _services(
        _result(
            account_id="acct-1",
            conversation_id="conv-other",
            status="succeeded",
            reason="completed",
            final_output="答案",
        )
    )
    with pytest.raises(NotFoundError):
        await get_run_replay(
            conversation_id=_CONVERSATION_ID,
            run_id=_RUN_ID,
            account_id="acct-1",
            services=services,
        )


# ---- resume 路由（轻量断线续传：重新获取租约 + 快照/事件 + 未闭环副作用 action） ----


class _FakePending:
    """resume 响应里的最小 pending action 替身（只提供 model_dump）。"""

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        del mode
        return {"action_id": "a1", "tool_name": "send_email"}


def _resume_services(
    result: SimpleNamespace | None, *, resumed: bool, pending: list[object] | None = None
) -> SimpleNamespace:
    async def require_owned(account_id: str, conversation_id: str) -> None:
        del account_id, conversation_id

    async def resume(run_id: str) -> SimpleNamespace | None:
        del run_id
        return SimpleNamespace() if resumed else None

    async def query(run_id: str, *, after_seq: int = 0) -> SimpleNamespace | None:
        del run_id, after_seq
        return result

    async def pending_actions(run_id: str) -> list[object]:
        del run_id
        return pending or []

    return SimpleNamespace(
        conversation_service=SimpleNamespace(require_owned=require_owned),
        run_service=SimpleNamespace(resume=resume, query=query, pending_actions=pending_actions),
    )


async def test_resume_reacquires_lease_and_reports_pending() -> None:
    services = _resume_services(
        _result(account_id="acct-1", status="succeeded", reason="completed", final_output="答案"),
        resumed=True,
        pending=[_FakePending()],
    )
    resp = await resume_run(
        conversation_id=_CONVERSATION_ID,
        run_id=_RUN_ID,
        account_id="acct-1",
        services=services,
    )
    assert resp.run_id == _RUN_ID
    assert resp.lease_reacquired is True
    assert resp.has_inflight_side_effects is True
    assert resp.pending_actions == [{"action_id": "a1", "tool_name": "send_email"}]


async def test_resume_unknown_run_returns_404() -> None:
    services = _resume_services(None, resumed=False)
    with pytest.raises(NotFoundError):
        await resume_run(
            conversation_id=_CONVERSATION_ID,
            run_id=_RUN_ID,
            account_id="acct-1",
            services=services,
        )


async def test_resume_cross_account_returns_404() -> None:
    services = _resume_services(
        _result(account_id="acct-2", status="succeeded", reason="completed", final_output="答案"),
        resumed=True,
    )
    with pytest.raises(NotFoundError):
        await resume_run(
            conversation_id=_CONVERSATION_ID,
            run_id=_RUN_ID,
            account_id="acct-1",
            services=services,
        )


async def test_resume_wrong_conversation_returns_404() -> None:
    """run_id 属于另一个会话（同账号）→ 404，不跨会话续传运行数据。"""
    services = _resume_services(
        _result(
            account_id="acct-1",
            conversation_id="conv-other",
            status="succeeded",
            reason="completed",
            final_output="答案",
        ),
        resumed=True,
    )
    with pytest.raises(NotFoundError):
        await resume_run(
            conversation_id=_CONVERSATION_ID,
            run_id=_RUN_ID,
            account_id="acct-1",
            services=services,
        )
