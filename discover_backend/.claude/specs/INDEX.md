# 专项规范索引

本目录存放按任务加载的工程规范，不是可执行命令。全局红线以仓库根目录 `AGENTS.md` / `CLAUDE.md` 为准，当前架构与路径以 `.ai/ARCHITECTURE.md` / `.ai/MODULE_MAP.md` 为准。

## 加载原则

- 任务明确命中某一职责时，只读取对应规范。
- 跨两个职责的改动可同时读取两份；不要默认加载整个目录。
- 不确定归属时，先读 `platform-architecture-spec.md`，再选择专项规范。
- 规范之间冲突时，按根目录全局规则的优先级处理。

## 任务映射

| 任务 | 规范 |
|---|---|
| 模块归属、分层、依赖方向、目录调整 | `platform-architecture-spec.md` |
| AGENT / SKILL 清单、资源归属、加载校验 | `agent-package-spec.md` |
| SkillResolver、SkillAssembler、AssemblyPlan、系统提示拼接 | `skill-assembly-spec.md` |
| 模型提供方、LLM 客户端、流式分片、thinking、usage | `llm-provider-spec.md` |
| MCP 注册表、capability、连接生命周期、failover / fallback | `mcp-integration-spec.md` |
| 工具目录、三级暴露、命名空间、分发、read_reference | `tool-broker-spec.md` |
| 白名单脚本、标准流、子进程、产物与超时 | `script-execution-spec.md` |
| SSE 帧、打字机、心跳、背压和终态 | `sse-streaming-spec.md` |

## 维护规则

- 一份规范只负责一个稳定主题，不记录临时状态、日期、端口或当前提供方。
- 新增规范前先确认现有文件无法承载该职责。
- 文件必须包含“适用场景 / 不适用场景 / 职责边界与权威来源 / 本规范专属检查”。
- 文件名统一使用 `kebab-case`，技术规范优先使用 `*-spec.md`。
