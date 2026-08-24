"""HTTP 产物下载测试——依赖本地 PostgreSQL（产物元数据入库 upload_files 表）。"""

import httpx


async def test_artifact_download_headers(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    app, client = api_ctx
    session_id = await _create_session(app)
    artifact_id = await _register_artifact(app, session_id)
    response = await client.get(f"/api/v1/sessions/{session_id}/artifacts/{artifact_id}")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content == "# 报告".encode()
    # 归属不符 → 404
    other_session = await _create_session(app)
    other = await client.get(f"/api/v1/sessions/{other_session}/artifacts/{artifact_id}")
    assert other.status_code == 404


async def _create_session(app: object) -> str:
    services = app.state.services
    record = await services.sessions.create_session()
    return record.session_id


async def _register_artifact(app: object, session_id: str) -> str:
    services = app.state.services
    workspace = await services.sessions.workspace_for("finder")
    src = workspace.root / "报告.md"
    src.write_text("# 报告", encoding="utf-8")
    record = await services.sessions.register_artifact(
        session_id=session_id,
        agent_id="finder",
        source_path=src,
        filename="报告.md",
    )
    return record.artifact_id
