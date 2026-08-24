"""脚本执行器（L1，script-sandbox-spec §2 契约，P1 本地直跑）。

# pragma: 简化 — 可信内部脚本，P1 一律宿主 subprocess 直跑（sys.executable），
# 不做容器隔离；若将来对外开放脚本编辑，再引入轻量沙箱（2026-08 用户决策）。

契约不变：stdin 一次写入 JSON 后关闭；stdout 边读边限流；stderr 只进审计，
失败时取尾部进上下文；超时先 SIGTERM（宽限内允许 flush）再 SIGKILL。
Windows 上 TerminateProcess 无优雅语义，等效硬杀，行为一致。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from pydantic import BaseModel, Field

from platform_engine.config.settings import Settings
from platform_engine.errors.base import ScriptError

logger = logging.getLogger(__name__)

# 平台注入脚本的环境变量契约（agent-package-spec §9：脚本唯一取路径方式）
# 仅两个：SKILL_ROOT_DIR（只读技能资产）、WORKSPACE_DIR（可写工作目录）。
ENV_SKILL_ROOT_DIR = "SKILL_ROOT_DIR"
ENV_WORKSPACE_DIR = "WORKSPACE_DIR"

_STDIN_LIMIT_BYTES = 1024 * 1024  # 入参 JSON 上限（字节）


class ScriptExecution(BaseModel):
    """一次脚本执行结果。"""

    exit_code: int
    stdout: str
    stderr_tail: str = ""
    produced_files: list[Path] = Field(default_factory=list)
    duration_ms: int = 0
    timed_out: bool = False
    output_overflow: bool = False


@dataclass
class _StreamState:
    """边读边限流状态（内部运行句柄）。"""

    # pragma: 简化 — 内部运行句柄，不跨边界，无需 pydantic
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)
    out_overflow: bool = False
    err_overflow: bool = False


def _scan_workspace(root: Path) -> dict[str, tuple[float, int]]:
    """执行前后扫描工作区：相对路径 → (mtime, size)。"""
    result: dict[str, tuple[float, int]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = (stat.st_mtime, stat.st_size)
    return result


class ScriptExecutor:
    """本地脚本执行器。跨会话复用；每次调用按工作区隔离（仅路径语义）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ---- 命令与运行环境构造（纯函数，可单测） ----
    def build_local_command(self, *, script_host: Path) -> list[str]:
        """本地直跑命令：当前解释器 + 脚本绝对路径。"""
        return [sys.executable, str(script_host)]

    def build_env(
        self,
        *,
        skill_dir: Path,
        workspace: Path,
        env_pairs: list[str],
    ) -> dict[str, str]:
        """运行环境：宿主环境 + 路径注入 + 清单白名单覆盖。"""
        env = dict(os.environ)
        env.update(
            {
                ENV_SKILL_ROOT_DIR: str(skill_dir),
                ENV_WORKSPACE_DIR: str(workspace),
                "PYTHONIOENCODING": "utf-8",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            }
        )
        for pair in env_pairs:
            key, sep, value = pair.partition("=")
            if sep and key:
                env[key] = value
        return env

    def _env_pairs(self, env_whitelist: list[str]) -> list[str]:
        """按清单白名单从宿主环境取值（本地直跑下为覆盖层，防宿主缺项）。"""
        pairs: list[str] = []
        for key in env_whitelist:
            value = os.environ.get(key)
            if value is not None:
                pairs.append(f"{key}={value}")
        return pairs

    # ---- 执行 ----
    async def run(
        self,
        *,
        host_script: Path,
        skill_dir: Path,
        workspace: Path,
        args: dict[str, object],
        env_whitelist: list[str],
        timeout_seconds: float,
    ) -> ScriptExecution:
        before = await anyio.to_thread.run_sync(_scan_workspace, workspace)
        env = self.build_env(
            skill_dir=skill_dir,
            workspace=workspace,
            env_pairs=self._env_pairs(env_whitelist),
        )
        command = self.build_local_command(script_host=host_script)
        payload = json.dumps(args, ensure_ascii=False).encode("utf-8")
        if len(payload) > _STDIN_LIMIT_BYTES:
            raise ScriptError(f"脚本入参超过上限（{_STDIN_LIMIT_BYTES} 字节）")
        logger.debug("启动脚本进程：%s，工作区=%s，入参 %d 字节", command, workspace, len(payload))
        start = time.perf_counter()
        try:
            process = await anyio.open_process(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workspace,
                env=env,
            )
        except OSError as exc:
            raise ScriptError(f"无法启动脚本进程：{exc}") from exc
        timed_out = False
        exit_code = 0
        state = _StreamState()
        try:
            assert process.stdin is not None
            await process.stdin.send(payload)
            await process.stdin.aclose()
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    self._drain,
                    process.stdout,
                    state,
                    "out",
                    self._settings.script_stream_limit_chars,
                )
                tg.start_soon(
                    self._drain,
                    process.stderr,
                    state,
                    "err",
                    self._settings.script_stream_limit_chars,
                )
                try:
                    with anyio.fail_after(timeout_seconds):
                        await process.wait()
                except TimeoutError:
                    timed_out = True
                    await self._terminate_process(process)
                finally:
                    if state.out_overflow or state.err_overflow:
                        await self._terminate_process(process)
                    exit_code = await process.wait()
        finally:
            await process.aclose()
        stdout = "".join(state.out)
        stderr_tail = "".join(state.err)[-self._settings.script_stderr_tail_chars :]
        after = await anyio.to_thread.run_sync(_scan_workspace, workspace)
        produced = self._produced_files(workspace, before, after)
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.debug(
            "脚本执行结束：exit=%d，%dms，timed_out=%s，overflow=%s，产物=%s",
            exit_code,
            duration_ms,
            timed_out,
            state.out_overflow or state.err_overflow,
            [str(path.relative_to(workspace)) for path in produced] or "（无）",
        )
        if stderr_tail:
            logger.debug("脚本 stderr 尾部：%s", stderr_tail)
        return ScriptExecution(
            exit_code=exit_code,
            stdout=stdout,
            stderr_tail=stderr_tail,
            produced_files=produced,
            duration_ms=duration_ms,
            timed_out=timed_out,
            output_overflow=state.out_overflow or state.err_overflow,
        )

    async def _drain(
        self,
        stream: anyio.abc.ByteReceiveStream | None,
        state: _StreamState,
        which: str,
        limit: int,
    ) -> None:
        """边读边限流；超限置位后立即停止读取（达限止损，防内存打爆）。"""
        if stream is None:
            return
        sink = state.out if which == "out" else state.err
        total = 0
        while True:
            try:
                chunk = await stream.receive()
            except anyio.EndOfStream:
                break
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                if which == "out":
                    state.out_overflow = True
                else:
                    state.err_overflow = True
                break
            sink.append(chunk.decode("utf-8", errors="replace"))

    async def _terminate_process(self, process: anyio.abc.Process) -> None:
        """超时/超限终止：先 SIGTERM（给 flush 缓冲的时间），宽限后 SIGKILL。"""
        try:
            process.terminate()
            with anyio.fail_after(self._settings.script_terminate_grace_seconds):
                await process.wait()
        except (TimeoutError, ProcessLookupError):
            process.kill()
            await process.wait()

    @staticmethod
    def _produced_files(
        workspace: Path,
        before: dict[str, tuple[float, int]],
        after: dict[str, tuple[float, int]],
    ) -> list[Path]:
        """对比执行前后三元组，新增或变化的文件即为产物。"""
        produced: list[Path] = []
        for rel, triple in after.items():
            if before.get(rel) != triple:
                produced.append((workspace / rel).resolve())
        return produced
