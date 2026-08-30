"""单元测试：ActiveTurnRegistry（stop 接口的服务器侧取消句柄注册表）。

纯本地：注册/注销/停止语义，无网络无 DB。取消目标用真实 asyncio.Task
验证 task.cancel() 生效。
"""

import asyncio
import contextlib

import anyio
from app.runtime.active_turns import ActiveTurn, ActiveTurnRegistry


def _turn(message_id: str = "msg-1") -> ActiveTurn:
    return ActiveTurn(message_id=message_id)


def test_register_get_unregister_roundtrip() -> None:
    reg = ActiveTurnRegistry()
    turn = _turn()
    assert reg.register("conv-1", turn) is True
    assert reg.get("conv-1") is turn
    reg.unregister("conv-1", turn)
    assert reg.get("conv-1") is None


def test_register_refuses_occupied_slot() -> None:
    """同会话已有句柄 → 拒绝且不覆盖（路由据此 409）。"""
    reg = ActiveTurnRegistry()
    assert reg.register("conv-1", _turn("a")) is True
    assert reg.register("conv-1", _turn("b")) is False
    kept = reg.get("conv-1")
    assert kept is not None and kept.message_id == "a"


def test_unregister_identity_guard() -> None:
    """身份比对：旧句柄 unregister 不得误删已替换的新句柄。"""
    reg = ActiveTurnRegistry()
    old = _turn("old")
    assert reg.register("conv-1", old) is True
    new = _turn("new")
    reg._turns["conv-1"] = new  # 测试探针：模拟替换（生产 register 拒绝替换）
    reg.unregister("conv-1", old)
    assert reg.get("conv-1") is new


async def test_request_stop_before_start_sets_flag_only() -> None:
    """未启动（task 为 None）：只置 stop_requested，不调 cancel。"""
    reg = ActiveTurnRegistry()
    turn = _turn()
    reg.register("conv-1", turn)
    assert reg.request_stop("conv-1") is turn
    assert turn.stop_requested is True
    assert turn.task is None


async def test_request_stop_cancels_running_task() -> None:
    """已启动：task.cancel() 使目标任务被取消；重复 stop 幂等。"""
    reg = ActiveTurnRegistry()
    turn = _turn()
    reg.register("conv-1", turn)
    task = asyncio.create_task(_spin_forever())
    turn.task = task
    assert reg.request_stop("conv-1") is turn
    with anyio.fail_after(1), contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()
    # 幂等：再次 stop 不抛错，仍返回句柄
    assert reg.request_stop("conv-1") is turn


async def test_request_stop_idle_when_absent() -> None:
    reg = ActiveTurnRegistry()
    assert reg.request_stop("conv-absent") is None


async def test_request_stop_skips_finished_task() -> None:
    """task 已结束：只置标记，对 done 任务 cancel 是 no-op（不抛）。"""
    reg = ActiveTurnRegistry()
    turn = _turn()
    reg.register("conv-1", turn)
    task = asyncio.create_task(_noop())
    await task
    assert task.done()
    turn.task = task
    assert reg.request_stop("conv-1") is turn
    assert turn.stop_requested is True


async def _spin_forever() -> None:
    await anyio.sleep_forever()


async def _noop() -> None:
    return None
