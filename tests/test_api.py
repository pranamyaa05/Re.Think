"""Integration and unit tests for Phase 1 components."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.database import engine


@pytest.fixture(autouse=True)
async def cleanup_db_connections():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "rethink-api"}


@pytest.mark.asyncio
async def test_create_and_get_user():
    username = f"cf_user_{uuid.uuid4().hex[:8]}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/users", json={"username": username})
        assert res.status_code == 201
        data = res.json()
        assert data["username"] == username
        user_id = data["id"]

        get_res = await ac.get(f"/api/users/{user_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == user_id


@pytest.mark.asyncio
async def test_platform_link_and_status():
    username = f"link_user_{uuid.uuid4().hex[:8]}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        u_res = await ac.post("/api/users", json={"username": username})
        assert u_res.status_code == 201
        user_id = u_res.json()["id"]

        link_res = await ac.post(
            "/api/platforms/link",
            json={"user_id": user_id, "platform": "codeforces", "handle": "tourist"}
        )
        assert link_res.status_code == 201
        link_id = link_res.json()["id"]
        assert link_res.json()["sync_status"] == "idle"

        st_res = await ac.get(f"/api/platforms/{link_id}/status")
        assert st_res.status_code == 200
        assert st_res.json()["handle"] == "tourist"

