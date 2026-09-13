"""核心边界与分层方向守卫（platform-architecture-spec §2 / §7）。

项目核心边界是 `LLM + Harness + Environment = Agent System`，DDD
（domain / application / infrastructure）只承载业务 CRUD。本文件用 AST 解析
`app/` 的 import 图，把边界写成可执行断言：

- `llm` 不依赖 harness / environment / DDD / interfaces；
- `environment` 不依赖 harness / DDD / interfaces；
- `harness` 依赖 llm 与 environment，但不依赖 DDD / interfaces；
- 三支柱都不得反向依赖 DDD 侧（domain / application）与 interfaces；
- `infrastructure` 是共享技术底座（DB / Redis / crypto / logging），四层与三支柱
  都可用它，但它不得依赖任何上层；
- DDD 侧：domain 零框架零 I/O；application 可驱动三支柱与 infrastructure；
- interfaces 只做协议适配，不得反向依赖组合根 bootstrap。

纯静态检查：只读源码，无网络、无 DB、无外部进程。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

APP_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "app"

# ── 核心边界：LLM / Harness / Environment ──────────────────────────────
CORE_LLM: Final[str] = "llm"
CORE_HARNESS: Final[str] = "harness"
CORE_ENVIRONMENT: Final[str] = "environment"

# DDD 侧（业务 CRUD）与横切层
DDD_LAYERS: Final[frozenset[str]] = frozenset({"domain", "application"})
BOTTOM_LAYER: Final[str] = "infrastructure"

CROSS_CUTTING: Final[frozenset[str]] = frozenset({"config", "shared"})

# 各层允许依赖的目标层（含自身）。
ALLOWED_TARGETS: Final[dict[str, frozenset[str]]] = {
    # L：模型接入只依赖自身与横切层
    CORE_LLM: frozenset({CORE_LLM}) | CROSS_CUTTING,
    # E：环境可用共享技术底座（DB / Redis / 存储实现）与 LLM 词汇
    CORE_ENVIRONMENT: frozenset({CORE_ENVIRONMENT, CORE_LLM, BOTTOM_LAYER}) | CROSS_CUTTING,
    # H：驱动层用 LLM 驱动环境
    CORE_HARNESS: frozenset({CORE_HARNESS, CORE_LLM, CORE_ENVIRONMENT}) | CROSS_CUTTING,
    # DDD：domain 纯领域；application 可驱动三支柱与基础设施
    "domain": frozenset({"domain"}) | CROSS_CUTTING,
    "application": frozenset(
        {"application", "domain", CORE_LLM, CORE_HARNESS, CORE_ENVIRONMENT, BOTTOM_LAYER}
    )
    | CROSS_CUTTING,
    # 共享技术底座：可用 domain 端口词汇，但不得依赖上层
    BOTTOM_LAYER: frozenset({BOTTOM_LAYER, "domain"}) | CROSS_CUTTING,
    # 接入层：协议适配，可用除 bootstrap 外所有层
    "interfaces": frozenset(
        {
            "interfaces",
            "application",
            "domain",
            CORE_LLM,
            CORE_HARNESS,
            CORE_ENVIRONMENT,
            BOTTOM_LAYER,
        }
    )
    | CROSS_CUTTING,
    "bootstrap": frozenset(
        {
            "bootstrap",
            "application",
            "domain",
            CORE_LLM,
            CORE_HARNESS,
            CORE_ENVIRONMENT,
            BOTTOM_LAYER,
            "interfaces",
        }
    )
    | CROSS_CUTTING,
    "config": frozenset({"config"}) | CROSS_CUTTING,
    "shared": frozenset({"shared"}),
}

# 三支柱：不得依赖 DDD 侧与接入层（核心边界不可反向）
CORE_PILLARS: Final[frozenset[str]] = frozenset({CORE_LLM, CORE_HARNESS, CORE_ENVIRONMENT})

# 领域层禁止出现的框架 / I/O 依赖（含子模块）。
DOMAIN_FORBIDDEN_PREFIXES: Final[tuple[str, ...]] = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "httpx",
    "redis",
    "anyio",
    "langgraph",
    "langchain_core",
    "argon2",
    "jwt",
    "uvicorn",
    "yaml",
)


def _python_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def _layer_of(path: Path) -> str | None:
    """文件所属层；顶层文件（app/main.py、app/__init__.py）返回 None。"""
    parts = path.relative_to(APP_ROOT).parts
    if len(parts) < 2:
        return None
    return parts[0]


def _imported_modules(path: Path) -> set[str]:
    """文件中所有 import 的模块名（含 `app.x` 绝对前缀形式）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(APP_ROOT)))
def test_layer_dependency_direction(path: Path) -> None:
    """每层的 import 目标必须落在白名单内（禁止反向 / 跨层越级）。"""
    layer = _layer_of(path)
    if layer is None or layer not in ALLOWED_TARGETS:
        pytest.skip(f"顶层文件不参与分层断言：{path.name}")
    allowed = ALLOWED_TARGETS[layer]
    violations: list[str] = []
    for module in sorted(_imported_modules(path)):
        if not module.startswith("app."):
            continue
        target = module.split(".")[1]
        if target not in ALLOWED_TARGETS:
            continue
        if target not in allowed:
            violations.append(f"{layer} → {target}（{module}）")
    assert not violations, f"{path.relative_to(APP_ROOT)} 存在违规依赖：{violations}"


def test_core_pillars_never_depend_on_ddd_side() -> None:
    """核心边界不可反向：LLM / Harness / Environment 不得依赖 DDD 侧与 interfaces。"""
    violations: list[str] = []
    for path in _python_files():
        layer = _layer_of(path)
        if layer not in CORE_PILLARS:
            continue
        for module in sorted(_imported_modules(path)):
            if not module.startswith("app."):
                continue
            target = module.split(".")[1]
            if target in DDD_LAYERS or target == "interfaces":
                violations.append(
                    f"{path.relative_to(APP_ROOT).as_posix()}：{layer} → {target}（{module}）"
                )
    assert not violations, f"三支柱反向依赖 DDD 侧：{violations}"


def test_llm_and_environment_are_not_coupled() -> None:
    """Environment 不得依赖 Harness（否则 `H = L + E` 变成双向环）。"""
    violations: list[str] = []
    for path in _python_files():
        if _layer_of(path) != CORE_ENVIRONMENT:
            continue
        for module in sorted(_imported_modules(path)):
            if module.startswith("app.harness"):
                violations.append(f"{path.relative_to(APP_ROOT).as_posix()}：{module}")
    assert not violations, f"environment 反向依赖 harness：{violations}"


def test_domain_has_no_framework_or_io_dependency() -> None:
    """domain 必须是纯领域层：不得 import 框架、数据库、HTTP 或外部 I/O 库。"""
    violations: list[str] = []
    for path in _python_files():
        if _layer_of(path) != "domain":
            continue
        offenders = sorted(
            module
            for module in _imported_modules(path)
            if module.split(".")[0] in DOMAIN_FORBIDDEN_PREFIXES
        )
        if offenders:
            violations.append(f"{path.relative_to(APP_ROOT).as_posix()}：{offenders}")
    assert not violations, f"domain 依赖了框架/IO 库：{violations}"


def test_interfaces_do_not_import_bootstrap() -> None:
    """接入层不得反向依赖组合根（依赖注入经 deps 取容器，而非 import bootstrap）。"""
    offenders = [
        path.relative_to(APP_ROOT).as_posix()
        for path in _python_files()
        if _layer_of(path) == "interfaces"
        and any(module.startswith("app.bootstrap") for module in _imported_modules(path))
    ]
    assert not offenders, f"interfaces 反向依赖 bootstrap：{offenders}"
