"""Integration and unit tests for Phase 1 components."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.config import settings
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
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["service"] == "rethink-api"


@pytest.mark.asyncio
async def test_create_and_get_user():
    username = f"cf_user_{uuid.uuid4().hex[:8]}"
    external_id = f"ext_{uuid.uuid4().hex}"
    headers = {"X-API-Key": settings.api_key, "X-External-Id": external_id}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        res = await ac.post(
            "/api/users",
            json={"username": username, "external_id": external_id},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["username"] == username
        user_id = data["id"]

        get_res = await ac.get(f"/api/users/{user_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == user_id


@pytest.mark.asyncio
async def test_platform_link_and_status():
    from unittest.mock import AsyncMock, patch

    username = f"link_user_{uuid.uuid4().hex[:8]}"
    external_id = f"ext_{uuid.uuid4().hex}"
    headers = {"X-API-Key": settings.api_key, "X-External-Id": external_id}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        u_res = await ac.post(
            "/api/users",
            json={"username": username, "external_id": external_id},
        )
        assert u_res.status_code == 201
        user_id = u_res.json()["id"]

        # Link creation must queue the sync and return immediately; the worker
        # itself is stubbed so this contract test never calls a platform API.
        with patch("app.routers.run_link_sync", new=AsyncMock()):
            link_res = await ac.post(
                "/api/platforms/link",
                json={"user_id": user_id, "platform": "codeforces", "handle": "tourist"}
            )
        assert link_res.status_code == 201
        link_id = link_res.json()["id"]
        assert link_res.json()["sync_status"] == "queued"

        st_res = await ac.get(f"/api/platforms/{link_id}/status")
        assert st_res.status_code == 200
        assert st_res.json()["handle"] == "tourist"


@pytest.mark.asyncio
async def test_analytics_endpoints():
    username = f"analytics_user_{uuid.uuid4().hex[:8]}"
    external_id = f"ext_{uuid.uuid4().hex}"
    headers = {"X-API-Key": settings.api_key, "X-External-Id": external_id}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        u_res = await ac.post(
            "/api/users",
            json={"username": username, "external_id": external_id},
        )
        assert u_res.status_code == 201
        user_id = u_res.json()["id"]

        # 1. Recompute on new user (0 solves)
        rec_res = await ac.post(f"/api/analytics/{user_id}/recompute")
        assert rec_res.status_code == 200
        rec_data = rec_res.json()
        assert rec_data["user_id"] == user_id
        assert rec_data["total_problems_solved"] == 0
        assert rec_data["status"] == "success"

        # 2. Get summary
        sum_res = await ac.get(f"/api/analytics/{user_id}/summary")
        assert sum_res.status_code == 200
        sum_data = sum_res.json()
        assert sum_data["user_id"] == user_id
        assert sum_data["total_problems_solved"] == 0
        assert "contest_summary" in sum_data

        # 3. Get topics
        top_res = await ac.get(f"/api/analytics/{user_id}/topics?min_samples=0")
        assert top_res.status_code == 200
        assert isinstance(top_res.json(), list)

        # 4. Get difficulty
        diff_res = await ac.get(f"/api/analytics/{user_id}/difficulty")
        assert diff_res.status_code == 200
        assert "buckets" in diff_res.json()

        # 5. Get contests
        cont_res = await ac.get(f"/api/analytics/{user_id}/contests")
        assert cont_res.status_code == 200
        assert cont_res.json()["contest_count"] == 0

        # 6. Another user's id is rejected by the ownership check
        bad_res = await ac.get("/api/analytics/999999/summary")
        assert bad_res.status_code == 403
