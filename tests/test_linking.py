"""Linking, identity resolution, and sync-status tests.

Covers the work finished in this session:

* POST /api/platforms/link validates Codeforces handles via user.info and
  returns 422 "Handle not found on Codeforces" for bad handles.
* Handles are normalized (trimmed, canonical casing from the platform API).
* Optional LeetCode session cookie: raw value accepted, a leading
  ``LEETCODE_SESSION=`` and quotes stripped, encrypted at rest, never returned.
* Links without a LeetCode cookie report submissions_available=false.
* POST /api/platforms/link starts the sync in the background and returns
  immediately; GET /platforms/{id}/status polls syncing -> synced with honest
  progress counts.
* GET /api/me returns the resolved user with their links and sync status.
* POST /api/users/resolve is idempotent and resolves the pre-existing
  identity on backend user 268.
"""

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.adapters.codeforces import CodeforcesAPIError
from app.config import settings
from app.database import async_session_factory, engine
from app.main import app
from app.models.platform_link import PlatformLink
from app.models.submission import Submission
from app.models.user import User
from app.utils.crypto import decrypt_token


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


def _headers(external_id: str) -> dict:
    return {"X-API-Key": settings.api_key, "X-External-Id": external_id}


async def _new_user(external_id: str) -> int:
    async with async_session_factory() as session:
        user = User(
            username=f"linktest_{uuid.uuid4().hex[:10]}", external_id=external_id
        )
        session.add(user)
        await session.commit()
        return user.id


def _cf_submission(sub_id: int) -> dict:
    """Minimal Codeforces user.status item."""
    return {
        "id": sub_id,
        "contestId": 100,
        "creationTimeSeconds": 1700000000 + sub_id,
        "relativeTimeSeconds": 1000,
        "problem": {
            "contestId": 100,
            "index": "A",
            "name": f"Problem 100A",
            "rating": 1500,
            "tags": [],
        },
        "author": {"participantType": "PRACTICE"},
        "programmingLanguage": "GNU C++20",
        "verdict": "OK",
        "passedTestCount": 10,
    }


@pytest.mark.asyncio
async def test_bad_codeforces_handle_returns_422():
    ext = f"oauth_badcf_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    try:
        with patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_info",
            new=AsyncMock(side_effect=CodeforcesAPIError("User not found")),
        ), patch("app.routers.run_link_sync", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_headers(ext),
            ) as ac:
                res = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "codeforces",
                        "handle": "Definitely_Not_A_Real_Handle_XYZ",
                    },
                )
        assert res.status_code == 422, res.text
        assert "Handle not found on Codeforces" in res.json()["detail"]

        async with async_session_factory() as session:
            count = await session.execute(
                select(PlatformLink).where(PlatformLink.user_id == user_id)
            )
            assert count.scalars().all() == []
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_codeforces_handle_normalized_to_canonical_casing():
    ext = f"oauth_normcf_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    link_id = None
    try:
        with patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_info",
            new=AsyncMock(return_value={"handle": "Tourist"}),
        ), patch("app.routers.run_link_sync", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_headers(ext),
            ) as ac:
                res = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "codeforces",
                        "handle": "tourist",
                    },
                )
        assert res.status_code == 201, res.text
        link_id = res.json()["id"]
        assert res.json()["handle"] == "Tourist"

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    select(PlatformLink).where(PlatformLink.id == link_id)
                )
            ).scalar_one()
            assert row.handle == "Tourist"
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(
                    delete(PlatformLink).where(PlatformLink.id == link_id)
                )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()



@pytest.mark.asyncio
async def test_leetcode_cookie_prefix_and_quotes_stripped():
    ext = f"oauth_lcstrip_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    link_id = None
    try:
        with patch(
            "app.adapters.leetcode.LeetCodeAdapter.get_authenticated_user",
            new=AsyncMock(
                return_value={"username": "lc_canonical", "isSignedIn": True}
            ),
        ), patch("app.routers.run_link_sync", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_headers(ext),
            ) as ac:
                res = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "leetcode",
                        "handle": "lc_canonical",
                        "auth_token": '"LEETCODE_SESSION=  raw_session_value  "',
                    },
                )
        assert res.status_code == 201, res.text
        link_id = res.json()["id"]

        async with async_session_factory() as session:
            row = (
                await session.execute(
                    select(PlatformLink).where(PlatformLink.id == link_id)
                )
            ).scalar_one()
            assert row.auth_token is not None
            decrypted = decrypt_token(row.auth_token)
            assert decrypted == "raw_session_value", repr(decrypted)
            assert "raw_session_value" not in row.auth_token
            assert "LEETCODE_SESSION" not in row.auth_token
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(
                    delete(PlatformLink).where(PlatformLink.id == link_id)
                )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_leetcode_submissions_available_without_cookie():
    ext = f"oauth_lcnc_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    link_id = None
    try:
        with patch(
            "app.adapters.leetcode.LeetCodeAdapter.get_user_profile",
            new=AsyncMock(
                return_value={
                    "username": "pub_handle",
                    "submitStats": {"acSubmissionNum": []},
                }
            ),
        ), patch("app.routers.run_link_sync", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_headers(ext),
            ) as ac:
                res = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "leetcode",
                        "handle": "pub_handle",
                    },
                )
                assert res.status_code == 201, res.text
                body = res.json()
                link_id = body["id"]
                assert body["submissions_available"] is False
                assert body["message"] is not None
                assert "session cookie" in body["message"]

                # A second LeetCode link for the same user/platform is rejected.
                res2 = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "leetcode",
                        "handle": "other_handle",
                        "auth_token": "some_cookie",
                    },
                )
                assert res2.status_code == 400
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(
                    delete(PlatformLink).where(PlatformLink.id == link_id)
                )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_me_returns_user_links_and_sync_status():
    ext = f"oauth_me_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    link_id = None
    try:
        with patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_info",
            new=AsyncMock(return_value={"handle": "tourist"}),
        ), patch("app.routers.run_link_sync", new=AsyncMock()):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_headers(ext),
            ) as ac:
                link_res = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "codeforces",
                        "handle": "tourist",
                    },
                )
                assert link_res.status_code == 201
                link_id = link_res.json()["id"]

                me = await ac.get("/api/me")
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["id"] == user_id
        assert body["external_id"] == ext
        assert len(body["links"]) == 1
        assert body["links"][0]["id"] == link_id
        assert body["links"][0]["sync_status"] == "queued"
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(
                    delete(PlatformLink).where(PlatformLink.id == link_id)
                )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_resolve_identity_twice_same_user():
    ext = f"oauth_idem_{uuid.uuid4().hex}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_headers(ext),
    ) as ac:
        first = await ac.post("/api/users/resolve", json={"external_id": ext})
        assert first.status_code == 200
        uid = first.json()["id"]
        second = await ac.post("/api/users/resolve", json={"external_id": ext})
        assert second.status_code == 200
        assert second.json()["id"] == uid
    async with async_session_factory() as session:
        await session.execute(delete(User).where(User.id == uid))
        await session.commit()


@pytest.mark.asyncio
async def test_resolve_preexisting_identity_returns_user_268():
    ext = "leetcode_Pranamyaa"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_headers(ext),
    ) as ac:
        res = await ac.post("/api/users/resolve", json={"external_id": ext})
    assert res.status_code == 200, res.text
    assert res.json()["id"] == 268, res.json()


@pytest.mark.asyncio
async def test_cf_link_sync_polling_syncing_to_synced():
    ext = f"oauth_syncpoll_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    link_id = None
    try:
        fake_sub = _cf_submission(1)
        with patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_info",
            new=AsyncMock(return_value={"handle": "tourist"}),
        ), patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_rating",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_status",
            new=AsyncMock(return_value=[fake_sub]),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_headers(ext),
            ) as ac:
                link_res = await ac.post(
                    "/api/platforms/link",
                    json={
                        "user_id": user_id,
                        "platform": "codeforces",
                        "handle": "tourist",
                    },
                )
                assert link_res.status_code == 201, link_res.text
                link_id = link_res.json()["id"]
                assert link_res.json()["sync_status"] == "queued"

                status = None
                row = None
                for _ in range(30):
                    st = await ac.get(f"/api/platforms/{link_id}/status")
                    assert st.status_code == 200
                    row = st.json()
                    status = row["sync_status"]
                    if status == "synced":
                        break
                    await asyncio.sleep(0.3)
                assert status == "synced", f"expected synced, got {status}: {row}"
                assert row["submissions_fetched"] >= 1
                assert row["submissions_inserted"] >= 1
                assert row["sync_error"] is None

        async with async_session_factory() as session:
            subs = (
                await session.execute(
                    select(Submission).where(
                        Submission.user_id == user_id,
                        Submission.platform == "codeforces",
                    )
                )
            ).scalars().all()
            assert len(subs) >= 1
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(
                    delete(PlatformLink).where(PlatformLink.id == link_id)
                )
            await session.execute(
                delete(Submission).where(Submission.user_id == user_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


def test_me_response_accepts_links_keyword():
    """MeResponse can be built directly with links=[...] as well as from the
    ORM relationship — the validation alias must not swallow the keyword."""
    from app.schemas import MeResponse

    me = MeResponse(
        id=1,
        username="u",
        external_id="ext",
        created_at=datetime(2026, 1, 1),
        links=[],
    )
    assert me.links == []
    dumped = me.model_dump()
    assert "links" in dumped
    assert dumped["links"] == []

