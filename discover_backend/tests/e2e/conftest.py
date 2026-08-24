import httpx
import pytest

# 端到端测试依赖本地开发服务器在跑（uvicorn platform_engine.api.app:create_app --factory）
LOCAL_BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture()
def base_url() -> str:
    return LOCAL_BASE_URL


@pytest.fixture()
async def api_client() -> httpx.AsyncClient:
    """真实服务客户端；服务未启动时整层跳过（CI 不因此红）。"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
        try:
            await client.get(LOCAL_BASE_URL, timeout=2.0)
        except httpx.HTTPError:
            pytest.skip(f"本地服务未启动（{LOCAL_BASE_URL}），跳过 e2e 测试")
        yield client
