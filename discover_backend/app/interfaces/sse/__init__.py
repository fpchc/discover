"""SSE 协议适配：RunEvent → 对外帧（event 判别），不含业务规则。"""

from app.interfaces.sse.frames import is_terminal, map_run_event

__all__ = ["is_terminal", "map_run_event"]
