"""Identity mapping, ownership enforcement and background-sync tests.

These cover the login/security contract added for the OAuth frontend:

* ``POST /api/users/resolve`` is idempotent, creates on first sight, and
  rejects a body identity that differs from the verified header.
* A verified identity may only read the user it maps to (403 otherwise).
* Creating a platform link returns immediately with ``sync_status='queued'``
  and schedules the sync in the background.
* The list endpoints the UI needs (current user, links, coach sessions,
  reflections by range) exist and enforce ownership.
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.config import settings
from app.database import async_session_factory, engine
from app.main import app
from app.models.hint_session import HintSession
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.reflection import Reflection
from app.models.user import User


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


def _headers(external_id: str) -> dict:
    return {"X-API-Key": settings.api_key, "X-External-Id": external_id}


async def _new_user(external_id: str) -> int:
    async with async_session_factory() as session:
        user = User(username=f"idtest_{uuid.uuid4().hex[:10]}", external_id=external_id)
        session.add(user)
        await session.commit()
        return user.id


@pytest.mark.asyncio
async def test_resolve_is_idempotent_and_creates_new_identity():
    ext = f"oauth_test_{uuid.uuid4().hex}"
    created_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=_headers(ext)
        ) as ac:
            first = await ac.post("/api/users/resolve", json={"external_id": ext})
            assert first.status_code == 200
            created_id = first.json()["id"]
            assert first.json()["external_id"] == ext

            second = await ac.post("/api/users/resolve", json={"external_id": ext})
            assert second.status_code == 200
            assert second.json()["id"] == created_id

            me = await ac.get("/api/users/me")
            assert me.status_code == 200
            assert me.json()["id"] == created_id
    finally:
        if created_id is not None:
            async with async_session_factory() as session:
                await session.execute(delete(User).where(User.id == created_id))
                await session.commit()


@pytest.mark.asyncio
async def test_resolve_rejects_identity_that_does_not_match_header():
    ext = f"oauth_test_{uuid.uuid4().hex}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=_headers(ext)
    ) as ac:
        res = await ac.post(
            "/api/users/resolve", json={"external_id": "somebody_else_entirely"}
        )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_cross_user_read_is_forbidden():
    owner_ext = f"oauth_owner_{uuid.uuid4().hex}"
    other_ext = f"oauth_other_{uuid.uuid4().hex}"
    owner_id = await _new_user(owner_ext)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_headers(other_ext),
        ) as ac:
            # Another identity asking for the owner's summary must be rejected.
            res = await ac.get(f"/api/analytics/{owner_id}/summary")
            assert res.status_code == 403
            # Even a plain user read is rejected.
            res = await ac.get(f"/api/users/{owner_id}")
            assert res.status_code == 403
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(User).where(User.id == owner_id))
            await session.commit()


@pytest.mark.asyncio
async def test_owner_can_read_their_own_user():
    ext = f"oauth_owner_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=_headers(ext)
        ) as ac:
            res = await ac.get(f"/api/users/{user_id}")
            assert res.status_code == 200
            assert res.json()["id"] == user_id
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_link_creation_queues_background_sync_and_returns_immediately():
    from unittest.mock import AsyncMock, patch

    ext = f"oauth_link_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    link_id = None
    try:
        fake_sync = AsyncMock()
        with patch(
            "app.adapters.codeforces.CodeforcesAdapter.get_user_info",
            new=AsyncMock(return_value={"handle": "tourist"}),
        ), patch("app.routers.run_link_sync", new=fake_sync):
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
                assert res.status_code == 201
                body = res.json()
                link_id = body["id"]
                assert body["sync_status"] == "queued"

                # Polling endpoint is reachable for the owner.
                status_res = await ac.get(f"/api/platforms/{link_id}/status")
                assert status_res.status_code == 200
                assert status_res.json()["sync_status"] == "queued"

                # Links are listable for the owner.
                list_res = await ac.get(f"/api/platforms?user_id={user_id}")
                assert list_res.status_code == 200
                assert [l["id"] for l in list_res.json()] == [link_id]

        # The background worker was scheduled with this exact link.
        fake_sync.assert_awaited_once_with(link_id)
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(delete(PlatformLink).where(PlatformLink.id == link_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_cross_user_link_status_is_forbidden():
    ext_owner = f"oauth_lowner_{uuid.uuid4().hex}"
    ext_other = f"oauth_lother_{uuid.uuid4().hex}"
    user_id = await _new_user(ext_owner)
    link_id = None
    try:
        async with async_session_factory() as session:
            link = PlatformLink(
                user_id=user_id,
                platform="codeforces",
                handle="tourist",
                sync_status="idle",
            )
            session.add(link)
            await session.commit()
            link_id = link.id

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_headers(ext_other),
        ) as ac:
            assert (await ac.get(f"/api/platforms/{link_id}/status")).status_code == 403
            assert (
                await ac.post(f"/api/platforms/{link_id}/sync")
            ).status_code == 403
            assert (await ac.delete(f"/api/platforms/{link_id}")).status_code == 403
    finally:
        async with async_session_factory() as session:
            if link_id is not None:
                await session.execute(delete(PlatformLink).where(PlatformLink.id == link_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_coach_sessions_and_reflections_are_listable_by_range():
    ext = f"oauth_lists_{uuid.uuid4().hex}"
    user_id = await _new_user(ext)
    problem_id = None
    session_id = None
    try:
        async with async_session_factory() as session:
            problem = Problem(
                platform="codeforces",
                platform_id=f"list_{uuid.uuid4().hex[:8]}",
                title="Listable Problem",
                rating=1200,
            )
            session.add(problem)
            await session.flush()

            hint = HintSession(
                user_id=user_id,
                problem_id=problem.id,
                current_level=1,
                coach_mode="socratic_nudge",
                outcome="ongoing",
            )
            session.add(hint)

            session.add(
                Reflection(
                    user_id=user_id,
                    date=date(2026, 10, 1),
                    content="A reflection in range.",
                    metrics={"problems_solved": 2},
                )
            )
            session.add(
                Reflection(
                    user_id=user_id,
                    date=date(2026, 9, 1),
                    content="Outside the range.",
                    metrics={},
                )
            )
            await session.commit()
            problem_id = problem.id
            session_id = hint.id

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=_headers(ext)
        ) as ac:
            sessions_res = await ac.get(f"/api/coach/sessions?user_id={user_id}")
            assert sessions_res.status_code == 200
            payload = sessions_res.json()
            assert [s["id"] for s in payload] == [session_id]
            assert payload[0]["problem_title"] == "Listable Problem"

            refl_res = await ac.get(
                f"/api/reflections?user_id={user_id}&from=2026-09-15&to=2026-10-20"
            )
            assert refl_res.status_code == 200
            items = refl_res.json()
            assert len(items) == 1
            assert items[0]["date"] == "2026-10-01"

            # Another identity cannot list them.
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_headers(f"oauth_other_{uuid.uuid4().hex}"),
        ) as ac:
            assert (
                await ac.get(f"/api/coach/sessions?user_id={user_id}")
            ).status_code == 403
            assert (
                await ac.get(f"/api/reflections?user_id={user_id}")
            ).status_code == 403
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(Reflection).where(Reflection.user_id == user_id)
            )
            if session_id is not None:
                await session.execute(
                    delete(HintSession).where(HintSession.id == session_id)
                )
            if problem_id is not None:
                await session.execute(delete(Problem).where(Problem.id == problem_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
