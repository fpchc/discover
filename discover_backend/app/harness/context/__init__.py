"""Harness 上下文编译器（P1#9 边界拆分）。

单一动机：把「模型本轮能看到什么」的确定性构造（ContextAssembler）与投影
（ContextProjector）从 environment 拆出。来源端口（会话 / 附件）与上下文事实模型
仍归 `app.environment.context`——回答「系统有哪些事实」；本包只回答「本轮如何取舍、
裁剪、压缩、注入并投影为模型消息」。依赖方向固定为 harness → environment（来源端口）。

对外 Facade：ContextAssembler / ContextProjector。
"""

from app.harness.context.assembler import ContextAssembler
from app.harness.context.projector import ContextProjector

__all__ = ["ContextAssembler", "ContextProjector"]
