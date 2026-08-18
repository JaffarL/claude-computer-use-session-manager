import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_frontend_and_static_assets_are_served_from_api_origin(
    api_client: AsyncClient,
) -> None:
    page = await api_client.get("/")
    stylesheet = await api_client.get("/static/app.css")
    script = await api_client.get("/static/app.js")

    assert page.status_code == 200
    assert "Computer Use 会话控制台" in page.text
    assert 'src="/static/app.js"' in page.text
    assert 'href="/static/app.css"' in page.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert "--accent: #b9f227" in stylesheet.text
    assert script.status_code == 200
    assert "new EventSource" in script.text
    assert "/vnc-access" in script.text


@pytest.mark.asyncio
async def test_unknown_static_asset_returns_not_found(api_client: AsyncClient) -> None:
    response = await api_client.get("/static/does-not-exist.js")

    assert response.status_code == 404
