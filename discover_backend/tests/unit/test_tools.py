"""Step 7 工具层测试。"""

import json
import sys
from pathlib import Path

import httpx
import pytest
from app.capabilities.mcp.client import (
    MCPCallResult,
    MCPClient,
    MCPToolInfo,
)
from app.capabilities.tools.broker import ToolBroker, ToolCallRequest, _coerce_nested_object_args
from app.capabilities.tools.descriptor import (
    ToolDescriptor,
    ToolSource,
    mcp_qualified_name,
    script_qualified_name,
    split_qualified_name,
    to_chat_tool_spec,
)
from app.capabilities.tools.script_executor import (
    ENV_SKILL_ROOT_DIR,
    ENV_WORKSPACE_DIR,
    ScriptExecution,
    ScriptExecutor,
    _scan_workspace,
)
from app.config.loader import MCPServer, MCPServerAuth
from app.config.settings import Settings, SideEffectType
from app.domain.skill.assemble import AssemblyPlan, CapabilityPlan
from app.domain.skill.manifest import ScriptDeclaration
from app.shared.errors.base import (
    ErrorCategory,
    MCPAuthError,
    MCPInvalidArgumentError,
    MCPRateLimitError,
    MCPTimeoutError,
)

MCP_SERVER = MCPServer(
    id="alibaba_search",
    transport="streamable_http",
    base_url="https://mcp.example.com",
    auth=MCPServerAuth(token_env="ALIBABA_SEARCH_TOKEN"),
    call_timeout_seconds=30,
    concurrency_limit=3,
)


def _mcp_client(handler: httpx.MockTransport) -> MCPClient:
    settings = Settings(_env_file=None)
    return MCPClient(
        MCP_SERVER, settings, api_key="k", http_client=httpx.AsyncClient(transport=handler)
    )


# ---- 描述符与命名空间 ----
def test_mcp_qualified_name_converts_hyphen() -> None:
    assert mcp_qualified_name("alibaba-search", "web_search") == "alibaba_search.web_search"
    assert mcp_qualified_name("alibaba_search", "web_search") == "alibaba_search.web_search"


def test_script_qualified_name() -> None:
    assert (
        script_qualified_name("discover", "client_finder", "score")
        == "discover.client_finder.script.score"
    )


def test_split_qualified_name() -> None:
    assert split_qualified_name("alibaba_search.web_search") == ("alibaba_search", "web_search")
    assert split_qualified_name("search_tools") == ("", "search_tools")


def test_to_chat_tool_spec_maps_fields() -> None:
    descriptor = ToolDescriptor(
        qualified_name="finder.research.script.run",
        short_name="run",
        namespace="finder.research.script",
        description="执行脚本",
        parameters={"type": "object"},
        source=ToolSource.SCRIPT,
        tier=1,
    )
    spec = to_chat_tool_spec(descriptor)
    assert spec.function.name == descriptor.qualified_name
    assert spec.function.description == descriptor.description
    assert spec.function.parameters == descriptor.parameters


# ---- MCP 客户端 ----
def _router_handler(
    *,
    init_status: int = 200,
    session_header: str | None = "sess-1",
) -> tuple[httpx.MockTransport, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        calls.append(method)
        if method == "initialize":
            headers = {"Mcp-Session-Id": session_header} if session_header else {}
            return httpx.Response(
                init_status,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"protocolVersion": "2025-03-26"},
                },
                headers=headers,
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            tools = [
                {
                    "name": "web_search",
                    "description": "网页搜索",
                    "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
                {
                    "name": "web_search_news",
                    "description": "新闻搜索",
                    "inputSchema": {"type": "object"},
                },
            ]
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": tools}}
            )
        if method == "tools/call":
            name = payload["params"]["name"]
            if name == "boom":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {
                            "content": [{"type": "text", "text": "执行失败"}],
                            "isError": True,
                        },
                    },
                )
            content: object = [{"type": "text", "text": "结果A"}]
            if name == "nothing":
                content = []
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"content": content},
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})

    return httpx.MockTransport(handler), calls


async def test_mcp_list_tools_and_session_header() -> None:
    transport, calls = _router_handler()
    async with _mcp_client(transport) as client:
        tools = await client.list_tools()
    assert [t.name for t in tools] == ["web_search", "web_search_news"]
    assert tools[0].input_schema["type"] == "object"
    assert "initialize" in calls and "notifications/initialized" in calls


async def test_mcp_call_tool_content() -> None:
    transport, _ = _router_handler()
    async with _mcp_client(transport) as client:
        result = await client.call_tool("web_search", {"q": "x"})
    assert result.content == "结果A"
    assert result.is_error is False


async def test_mcp_call_tool_empty_result_is_success() -> None:
    transport, _ = _router_handler()
    async with _mcp_client(transport) as client:
        result = await client.call_tool("nothing", {})
    assert result.content == ""
    assert result.is_error is False


async def test_mcp_call_tool_error_flag() -> None:
    transport, _ = _router_handler()
    async with _mcp_client(transport) as client:
        result = await client.call_tool("boom", {})
    assert result.is_error is True
    assert result.content == "执行失败"


async def test_mcp_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        return httpx.Response(401, json={"error": {"message": "bad token"}})

    async with _mcp_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(MCPAuthError):
            await client.list_tools()


async def test_mcp_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        return httpx.Response(429, json={"error": {"message": "too many"}})

    async with _mcp_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(MCPRateLimitError):
            await client.list_tools()


async def test_mcp_invalid_params_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad params"}},
        )

    async with _mcp_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(MCPInvalidArgumentError):
            await client.list_tools()


async def test_mcp_read_timeout_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        raise httpx.ReadTimeout("read timeout", request=request)

    async with _mcp_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(MCPTimeoutError):
            await client.list_tools()


async def test_mcp_sse_response_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        event = {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {"tools": [{"name": "sse_tool", "description": "ss", "inputSchema": {}}]},
        }
        sse = f"data: {json.dumps(event)}\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    async with _mcp_client(httpx.MockTransport(handler)) as client:
        tools = await client.list_tools()
    assert [t.name for t in tools] == ["sse_tool"]


# ---- 脚本执行器（本地直跑：命令/环境构造 + 真实 subprocess） ----
def test_script_local_command_build() -> None:
    executor = ScriptExecutor(Settings(_env_file=None))
    host = Path("C:/agents/finder/skills/research/scripts/run.py")
    cmd = executor.build_local_command(script_host=host)
    assert cmd == [sys.executable, str(host)]


def test_build_env_injects_paths_and_whitelist(tmp_path: Path) -> None:
    executor = ScriptExecutor(Settings(_env_file=None))
    skill_dir = tmp_path / "agents" / "finder" / "research"
    workspace = tmp_path / "workspaces" / "finder"
    env = executor.build_env(
        skill_dir=skill_dir,
        workspace=workspace,
        env_pairs=["ALIBABA_SEARCH_TOKEN=secret"],
    )
    assert env[ENV_SKILL_ROOT_DIR] == str(skill_dir)
    assert env[ENV_WORKSPACE_DIR] == str(workspace)
    assert env["ALIBABA_SEARCH_TOKEN"] == "secret"


async def test_script_local_run_subprocess(tmp_path: Path) -> None:
    """真实本地 subprocess 冒烟：读 stdin、写工作区、产物扫描（不依赖 Docker）。"""
    agent_dir = tmp_path / "agent"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skill_dir = agent_dir / "s1"
    script = skill_dir / "scripts" / "echo.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "print('echo:' + data['name'])\n"
        "open('out.txt', 'w').write(data['name'])\n",
        encoding="utf-8",
    )
    executor = ScriptExecutor(Settings(_env_file=None))
    result = await executor.run(
        host_script=script,
        skill_dir=skill_dir,
        workspace=workspace,
        args={"name": "hello"},
        env_whitelist=[],
        timeout_seconds=10.0,
    )
    assert result.exit_code == 0
    assert "echo:hello" in result.stdout
    assert result.produced_files == [(workspace / "out.txt").resolve()]


def test_script_produced_files_detection(tmp_path: Path) -> None:
    executor = ScriptExecutor(Settings(_env_file=None))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    existing = workspace / "a.txt"
    existing.write_text("x", encoding="utf-8")
    before = _scan_workspace(workspace)
    new_file = workspace / "out.csv"
    new_file.write_text("a,b\n", encoding="utf-8")
    after = _scan_workspace(workspace)
    produced = executor._produced_files(workspace, before, after)
    assert produced == [new_file.resolve()]


# ---- 工具代理 ----
class _FakeClient:
    call_timeout_seconds = 30.0

    def __init__(self, tools: list[MCPToolInfo], server_id: str) -> None:
        self.tools = tools
        self.server_id = server_id
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self) -> list[MCPToolInfo]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, object]) -> MCPCallResult:
        self.calls.append((name, arguments))
        if name == "boom":
            raise MCPTimeoutError("调用超时")
        return MCPCallResult(content=f"mcp:{name}")


class _FakeMCPManager:
    def __init__(self, tools: list[MCPToolInfo], *, fail: set[str] | None = None) -> None:
        self.tools = tools
        self.fail = fail or set()
        self.acquired: list[str] = []
        self.released: list[str] = []

    async def acquire(self, server_id: str) -> _FakeClient:
        if server_id in self.fail:
            raise MCPAuthError("认证失败")
        self.acquired.append(server_id)
        return _FakeClient(self.tools, server_id)

    def release(self, server_id: str) -> None:
        self.released.append(server_id)

    def concurrency_limit(self, server_id: str) -> int:
        return 2


class _FakeScriptExecutor:
    def __init__(self, execution: ScriptExecution | None = None) -> None:
        self.execution = execution or ScriptExecution(exit_code=0, stdout="script-ok")
        self.calls: list[dict[str, object]] = []

    async def run(self, **kwargs: object) -> ScriptExecution:
        self.calls.append(kwargs)
        return self.execution


def _plan() -> AssemblyPlan:
    return AssemblyPlan(
        agent_id="finder",
        skill_id="research",
        system_prompt="系统提示",
        required_mcp_servers=["alibaba_search"],
        optional_mcp_servers=[],
        mcp_degrade_notes={},
        core_tool_names=["web_search"],
        scripts=[
            ScriptDeclaration(
                path="scripts/run.py",
                name="run",
                description="执行调研脚本",
                side_effect=SideEffectType.WRITE_FILE,
            )
        ],
        env_whitelist=["API_KEY"],
    )


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    skill_dir = tmp_path / "finder" / "research"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (skill_dir / "references" / "guide.md").write_text("# 指南\n\n正文内容\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return skill_dir, workspace


def _broker(
    tmp_path: Path, mcp_manager: _FakeMCPManager, script_executor: _FakeScriptExecutor
) -> ToolBroker:
    settings = Settings(_env_file=None)
    return ToolBroker(settings=settings, mcp_manager=mcp_manager, script_executor=script_executor)


_MCP_TOOLS = [
    MCPToolInfo(name="web_search", description="网页搜索", input_schema={"type": "object"}),
    MCPToolInfo(name="web_search_news", description="新闻搜索", input_schema={"type": "object"}),
]


async def test_activate_three_tiers(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS)
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.started_services == ["alibaba_search"]
    names = set(broker._descriptors)  # type: ignore[attr-defined]
    assert {"search_tools", "describe_tool", "read_reference"} <= names
    assert "finder.research.script.run" in names
    assert "alibaba_search.web_search" in names
    assert "alibaba_search.web_search_news" in names
    exposed = {spec.function.name for spec in broker.exposed_tools()}
    assert "finder.research.script.run" in exposed
    assert "alibaba_search.web_search" in exposed  # 核心工具 Tier1
    assert "alibaba_search.web_search_news" not in exposed  # Tier2 懒加载

    catalog = broker.catalog_tool_names()
    assert "alibaba_search.web_search_news" in catalog  # 目录全集含 Tier2，供阶段白名单


async def test_activate_hides_generic_mcp_dispatch_tools(tmp_path: Path) -> None:
    """泛化分发工具（call_tool / call_tools_batch）不进入模型可见清单与目录。"""
    skill_dir, workspace = _setup(tmp_path)
    tools = [
        MCPToolInfo(name="call_tool", description="泛化调用", input_schema={"type": "object"}),
        MCPToolInfo(
            name="call_tools_batch", description="批量调用", input_schema={"type": "object"}
        ),
        MCPToolInfo(name="search_companies", description="查公司", input_schema={"type": "object"}),
    ]
    plan = _plan().model_copy(update={"core_tool_names": ["search_companies"]})
    broker = _broker(tmp_path, _FakeMCPManager(tools), _FakeScriptExecutor())
    activation = await broker.activate(
        plan=plan,
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    catalog = broker.catalog_tool_names()
    exposed = {spec.function.name for spec in broker.exposed_tools()}
    assert "alibaba_search.call_tool" not in catalog
    assert "alibaba_search.call_tools_batch" not in catalog
    assert "alibaba_search.call_tool" not in exposed
    assert "alibaba_search.search_companies" in catalog


async def test_catalog_tool_names_excludes_unactivated_server(tmp_path: Path) -> None:
    """catalog_tool_names 只含已激活服务的工具；未激活服务器的目录项不得进入白名单。"""
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    # 必填失败 → 激活失败，不应残留已激活目录项
    activation = await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is False
    # 仅剩元工具（search_tools/describe_tool/read_reference），MCP 工具不在目录
    catalog = set(broker.catalog_tool_names())
    assert "alibaba_search.web_search" not in catalog
    assert {"search_tools", "describe_tool", "read_reference"} <= catalog


async def test_activate_required_failure_releases(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is False
    assert activation.failed_required == ["alibaba_search"]
    assert activation.reason == "必需 MCP 依赖不可用，拒绝激活"


def _capability_plan(candidates: list[str], *, required: bool = True) -> AssemblyPlan:
    """仅含能力依赖的装配计划（failover 测试用）。"""
    return AssemblyPlan(
        agent_id="finder",
        skill_id="research",
        system_prompt="系统提示",
        capabilities=[
            CapabilityPlan(
                capability="web_search",
                candidate_servers=candidates,
                required=required,
            )
        ],
        env_whitelist=[],
    )


async def test_activate_capability_failover_switches_to_backup(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_capability_plan(["alibaba_search", "yuanbao_search"]),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.started_services == ["yuanbao_search"]
    assert activation.degraded_services == ["alibaba_search"]
    assert "yuanbao_search.web_search" in broker._descriptors  # type: ignore[attr-defined]
    assert "alibaba_search.web_search" not in broker._descriptors  # type: ignore[attr-defined]


async def test_activate_capability_required_all_fail_releases(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search", "yuanbao_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_capability_plan(["alibaba_search", "yuanbao_search"]),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is False
    assert activation.failed_required == ["alibaba_search", "yuanbao_search"]
    assert activation.reason == "必需依赖不可用，拒绝激活"
    assert manager.released == []


async def test_activate_capability_optional_all_fail_degrades(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search", "yuanbao_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_capability_plan(["alibaba_search", "yuanbao_search"], required=False),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.failed_required == []
    assert activation.degraded_services == ["alibaba_search", "yuanbao_search"]
    assert activation.reason is None


async def test_activate_capability_fallback_substitutes_search(tmp_path: Path) -> None:
    """主候选失败时降级到 fallback 能力候选服务器，且服务去重、降级说明由系统生成。"""
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    plan = AssemblyPlan(
        agent_id="finder",
        skill_id="research",
        system_prompt="系统提示",
        capabilities=[
            CapabilityPlan(
                capability="enterprise_business",
                candidate_servers=["alibaba_search"],
                required=False,
                fallback_capability="web_search",
                fallback_servers=["yuanbao_search"],
            ),
            CapabilityPlan(
                capability="web_search",
                candidate_servers=["yuanbao_search"],
                required=True,
            ),
        ],
        env_whitelist=[],
    )
    activation = await broker.activate(
        plan=plan,
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.started_services == ["yuanbao_search"]
    assert "enterprise_business" in activation.degraded_services
    # 服务只 acquire 一次（fallback 与 web_search 共享同一服务器时去重）
    assert manager.acquired == ["yuanbao_search"]
    # 降级说明由系统生成，包含降级目标能力
    note = [
        n
        for s, n in zip(activation.degraded_services, activation.degrade_notes, strict=True)
        if s == "enterprise_business"
    ]
    assert note and "web_search" in note[0]


async def test_activate_capability_fallback_all_fail_optional_continues(tmp_path: Path) -> None:
    """主候选与 fallback 全失败且能力非必需时，降级继续激活。"""
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search", "yuanbao_search"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    plan = AssemblyPlan(
        agent_id="finder",
        skill_id="research",
        system_prompt="系统提示",
        capabilities=[
            CapabilityPlan(
                capability="enterprise_business",
                candidate_servers=["alibaba_search"],
                required=False,
                fallback_capability="web_search",
                fallback_servers=["yuanbao_search"],
            )
        ],
        env_whitelist=[],
    )
    activation = await broker.activate(
        plan=plan,
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.failed_required == []
    assert activation.started_services == []
    assert set(activation.degraded_services) == {"alibaba_search", "yuanbao_search"}


async def test_execute_mcp_and_script_and_order(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS)
    script_executor = _FakeScriptExecutor()
    broker = _broker(tmp_path, manager, script_executor)
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    calls = [
        ToolCallRequest(call_id="c1", tool_name="alibaba_search.web_search", arguments={"q": "x"}),
        ToolCallRequest(
            call_id="c2", tool_name="finder.research.script.run", arguments={"input": "调研"}
        ),
    ]
    results = await broker.execute(calls)
    assert [r.call_id for r in results] == ["c1", "c2"]
    assert results[0].ok and results[0].content == "mcp:web_search"
    assert results[1].ok and results[1].content == "script-ok"


async def test_execute_unknown_tool_with_candidates(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor())
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="alibaba_search.web_sear", arguments={})],
    )
    assert results[0].ok is False
    assert results[0].error_category == ErrorCategory.NOT_FOUND
    assert results[0].suggestion is not None


async def test_execute_delete_side_effect_runs_directly(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    script_executor = _FakeScriptExecutor()
    plan = _plan().model_copy(
        update={
            "scripts": [
                ScriptDeclaration(
                    path="scripts/run.py",
                    name="run",
                    description="删除临时文件",
                    side_effect=SideEffectType.DELETE,
                )
            ]
        }
    )
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), script_executor)
    await broker.activate(
        plan=plan,
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="finder.research.script.run", arguments={})]
    )
    assert results[0].ok is True  # 删除副作用不再挂起审批，直接执行
    assert script_executor.calls


async def test_search_tools_no_params(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor())
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    hits = broker.search_tools("搜索 新闻")
    assert any(hit.qualified_name == "alibaba_search.web_search_news" for hit in hits)
    dumped = hits[0].model_dump()
    assert "parameters" not in dumped  # 检索不返回参数约束


def test_coerce_nested_object_args() -> None:
    """schema 声明为 object 的参数被模型序列化成 JSON 字符串时应回转为对象。

    回归防护：tyc_mcp.call_tool 的 arguments 字段声明为 object，但推理模型常把它
    连同外层一起 JSON 序列化成字符串，远端报「arguments must be an object」，
    导致正文采集全部失败、最终无正文输出。
    """
    descriptor = ToolDescriptor(
        qualified_name="tyc_mcp.call_tool",
        short_name="call_tool",
        namespace="tyc_mcp",
        description="分派工具",
        parameters={
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "tool_name": {"type": "string"},
                "arguments": {"type": "object"},
            },
        },
        source=ToolSource.MCP,
        tier=2,
    )
    args = {"company_name": "X", "tool_name": "get_annual_reports", "arguments": '{"page": 1}'}
    coerced = _coerce_nested_object_args(descriptor, args)
    assert coerced["arguments"] == {"page": 1}
    # 字符串字段（company_name / tool_name）不得被误解析
    assert coerced["company_name"] == "X"
    assert coerced["tool_name"] == "get_annual_reports"


def test_coerce_nested_object_args_batch_calls() -> None:
    """call_tools_batch 的 calls 数组（含嵌套 arguments 字符串）应逐项回转为对象。"""
    descriptor = ToolDescriptor(
        qualified_name="tyc_mcp.call_tools_batch",
        short_name="call_tools_batch",
        namespace="tyc_mcp",
        description="批量分派工具",
        parameters={},  # 无 properties：靠字段名确定性回退，不依赖 schema 声明
        source=ToolSource.MCP,
        tier=2,
    )
    args = {
        "company_name": "X",
        "calls": '[{"tool_name": "get_annual_reports", "arguments": "{\\"page\\": 1}"}]',
    }
    coerced = _coerce_nested_object_args(descriptor, args)
    calls = coerced["calls"]
    assert isinstance(calls, list)
    assert calls[0]["arguments"] == {"page": 1}


def test_coerce_nested_object_args_keeps_non_string_and_non_object() -> None:
    """非字符串值、schema 未声明为 object 的字段、非法 JSON 均原样保留。"""
    descriptor = ToolDescriptor(
        qualified_name="tyc_mcp.call_tool",
        short_name="call_tool",
        namespace="tyc_mcp",
        description="分派工具",
        parameters={
            "type": "object",
            "properties": {
                "arguments": {"type": "object"},
                "note": {"type": "string"},
            },
        },
        source=ToolSource.MCP,
        tier=2,
    )
    # 已是对象 → 不动
    assert _coerce_nested_object_args(descriptor, {"arguments": {"a": 1}})["arguments"] == {"a": 1}
    # schema 是 string 的字段 → 不解析（即使看起来像 JSON）
    assert _coerce_nested_object_args(descriptor, {"note": '{"a":1}'})["note"] == '{"a":1}'
    # 非法 JSON → 保留原字符串
    assert (
        _coerce_nested_object_args(descriptor, {"arguments": "not json"})["arguments"] == "not json"
    )


async def test_describe_tool_expands_exposed(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor())
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert "alibaba_search.web_search_news" not in {s.function.name for s in broker.exposed_tools()}
    results = await broker.execute(
        [
            ToolCallRequest(
                call_id="c1",
                tool_name="describe_tool",
                arguments={"qualified_name": "alibaba_search.web_search_news"},
            )
        ],
    )
    assert results[0].ok is True
    assert "alibaba_search.web_search_news" in {s.function.name for s in broker.exposed_tools()}


async def test_read_reference_traversal_rejected(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor())
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [
            ToolCallRequest(
                call_id="c1", tool_name="read_reference", arguments={"path": "../secret.txt"}
            )
        ],
    )
    assert results[0].ok is False
    assert results[0].error_category == ErrorCategory.INVALID_ARGUMENT


async def test_read_reference_valid_and_dedup(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor())
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="read_reference", arguments={"path": "guide.md"})],
    )
    assert results[0].ok is True
    assert "指南" in results[0].content
    second = await broker.execute(
        [ToolCallRequest(call_id="c2", tool_name="read_reference", arguments={"path": "guide.md"})],
    )
    assert "已在上下文" in second[0].content


async def test_error_classification_with_suggestion(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(
        [MCPToolInfo(name="boom", description="d", input_schema={})],
    )
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    plan = _plan().model_copy(
        update={"required_mcp_servers": ["alibaba_search"], "core_tool_names": ["boom"]}
    )
    await broker.activate(
        plan=plan,
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="alibaba_search.boom", arguments={})],
    )
    assert results[0].ok is False
    assert results[0].error_category == ErrorCategory.TIMEOUT
    assert results[0].suggestion == "缩小输入或分批"


async def test_script_produced_files_surfaced(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    produced = ScriptExecution(
        exit_code=0,
        stdout="done",
        produced_files=[(workspace / "out.csv").resolve()],
    )
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor(produced))
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="finder.research.script.run", arguments={})],
    )
    assert results[0].produced_files == ["out.csv"]


async def test_script_failure_surfaces_stdout_error_json(tmp_path: Path) -> None:
    """脚本失败时把 stdout 的 JSON 错误载荷透出（契约：失败信息走 stdout）。"""
    skill_dir, workspace = _setup(tmp_path)
    failed = ScriptExecution(
        exit_code=1,
        stdout='{"error": "报告 JSON 不存在（提示文本）"}',
    )
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor(failed))
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="finder.research.script.run", arguments={})],
    )
    assert results[0].ok is False
    assert results[0].error_category == ErrorCategory.SCRIPT
    assert "报告 JSON 不存在" in results[0].message
    assert "脚本退出码非 0" not in results[0].message


async def test_script_failure_falls_back_to_stderr(tmp_path: Path) -> None:
    """stdout 无错误载荷时回落 stderr 尾部；两者皆空才用退出码占位。"""
    skill_dir, workspace = _setup(tmp_path)
    failed = ScriptExecution(exit_code=1, stdout="", stderr_tail="stderr 详情")
    broker = _broker(tmp_path, _FakeMCPManager(_MCP_TOOLS), _FakeScriptExecutor(failed))
    await broker.activate(
        plan=_plan(),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    results = await broker.execute(
        [ToolCallRequest(call_id="c1", tool_name="finder.research.script.run", arguments={})],
    )
    assert results[0].ok is False
    assert "stderr 详情" in results[0].message


# ---- 能力策略 all：全部候选激活供 re-act 选调 ----
def _capability_all_plan(candidates: list[str], *, required: bool = True) -> AssemblyPlan:
    return AssemblyPlan(
        agent_id="finder",
        skill_id="research",
        system_prompt="系统提示",
        capabilities=[
            CapabilityPlan(
                capability="web_search",
                strategy="all",
                candidate_servers=candidates,
                required=required,
            )
        ],
        env_whitelist=[],
    )


async def test_activate_capability_all_activates_every_candidate(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS)
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_capability_all_plan(["alibaba_search", "tencent_mcp"]),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.started_services == ["alibaba_search", "tencent_mcp"]
    assert activation.degraded_services == []
    assert "alibaba_search.web_search" in broker._descriptors  # type: ignore[attr-defined]
    assert "tencent_mcp.web_search" in broker._descriptors  # type: ignore[attr-defined]


async def test_activate_capability_all_partial_failure_degrades_only_that_candidate(
    tmp_path: Path,
) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"tencent_mcp"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_capability_all_plan(["alibaba_search", "tencent_mcp"]),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is True
    assert activation.started_services == ["alibaba_search"]
    assert activation.degraded_services == ["tencent_mcp"]
    assert "alibaba_search.web_search" in broker._descriptors  # type: ignore[attr-defined]
    assert "tencent_mcp.web_search" not in broker._descriptors  # type: ignore[attr-defined]


async def test_activate_capability_all_required_all_fail_rejects(tmp_path: Path) -> None:
    skill_dir, workspace = _setup(tmp_path)
    manager = _FakeMCPManager(_MCP_TOOLS, fail={"alibaba_search", "tencent_mcp"})
    broker = _broker(tmp_path, manager, _FakeScriptExecutor())
    activation = await broker.activate(
        plan=_capability_all_plan(["alibaba_search", "tencent_mcp"]),
        skill_dir=skill_dir,
        workspace=workspace,
        session_id="s1",
        account_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert activation.ok is False
    assert set(activation.failed_required) == {"alibaba_search", "tencent_mcp"}
