"""
Phase 5A Tests: LeetCode Integration, Adapter, Schema, Verdict Normalization, and Sync.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from app.adapters.leetcode import (
    LeetCodeAdapter,
    LeetCodeAPIError,
    normalize_leetcode_verdict,
)
from app.database import async_session_factory, engine
from app.models.contest_performance import ContestPerformance
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services.analytics import AnalyticsService
from app.services.sync import CodeforcesSyncService, SyncAlreadyRunningError
from app.utils.crypto import decrypt_token, encrypt_token


@pytest.fixture(autouse=True)
async def cleanup_db():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_verdict_normalization():
    """Verify LeetCode verdicts are normalized at the adapter layer."""
    assert normalize_leetcode_verdict("Accepted") == "OK"
    assert normalize_leetcode_verdict("Wrong Answer") == "WRONG_ANSWER"
    assert normalize_leetcode_verdict("Time Limit Exceeded") == "TIME_LIMIT_EXCEEDED"
    assert normalize_leetcode_verdict("Memory Limit Exceeded") == "MEMORY_LIMIT_EXCEEDED"
    assert normalize_leetcode_verdict("Runtime Error") == "RUNTIME_ERROR"
    assert normalize_leetcode_verdict("Compile Error") == "COMPILATION_ERROR"
    assert normalize_leetcode_verdict("Output Limit Exceeded") == "OUTPUT_LIMIT_EXCEEDED"
    assert normalize_leetcode_verdict(None) == "UNKNOWN"
    assert normalize_leetcode_verdict("") == "UNKNOWN"


@pytest.mark.asyncio
async def test_token_encryption_roundtrip():
    """Verify sensitive auth tokens are encrypted and decrypted correctly."""
    plain = "test_leetcode_session_secret_cookie_12345"
    encrypted = encrypt_token(plain)
    assert encrypted is not None
    assert encrypted != plain
    assert "test_leetcode_session" not in encrypted

    decrypted = decrypt_token(encrypted)
    assert decrypted == plain

    assert encrypt_token(None) is None
    assert encrypt_token("") is None
    assert decrypt_token(None) is None
    assert decrypt_token("invalid_junk") is None


@pytest.mark.asyncio
async def test_leetcode_adapter_headers_and_cookie():
    """Verify LeetCode adapter correctly sets User-Agent, Referer, and Cookie headers."""
    adapter = LeetCodeAdapter()

    captured_headers = {}

    async def mock_post(client_self, url, json=None, headers=None, **kwargs):
        captured_headers.update(dict(client_self.headers))
        if headers:
            captured_headers.update(headers)
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {
            "data": {
                "matchedUser": {
                    "username": "test_user",
                    "profile": {"realName": "Tester", "ranking": 1, "userAvatar": ""},
                    "submitStats": {"acSubmissionNum": []},
                }
            }
        }
        return mock_resp

    with patch("httpx.AsyncClient.post", new=mock_post):
        res = await adapter.get_user_profile("test_user", auth_token="my_session_token")
        assert res["username"] == "test_user"
        cookie_val = captured_headers.get("cookie") or captured_headers.get("Cookie") or ""
        assert "LEETCODE_SESSION=my_session_token" in cookie_val
        referer_val = captured_headers.get("referer") or captured_headers.get("Referer") or ""
        assert referer_val == "https://leetcode.com"
        ua_val = captured_headers.get("user-agent") or captured_headers.get("User-Agent") or ""
        assert "Mozilla" in ua_val


@pytest.mark.asyncio
async def test_leetcode_sync_no_cookie():
    """
    Verify no-cookie mode:
    Populates contest performances from public data, but submissions table stays empty.
    """
    # 1. Create a test user and platform link
    async with async_session_factory() as session:
        user = User(username=f"lc_user_nocookie_{datetime.now().timestamp()}")
        session.add(user)
        await session.flush()

        link = PlatformLink(
            user_id=user.id,
            platform="leetcode",
            handle="test_lc_handle",
            auth_token=None,  # No cookie
            sync_status="idle",
        )
        session.add(link)
        await session.commit()
        user_id = user.id
        link_id = link.id

    # 2. Mock LeetCode adapter contest ranking
    mock_lc = LeetCodeAdapter()
    mock_lc.get_user_contest_ranking = AsyncMock(return_value={
        "ranking": {"attendedContestsCount": 2, "rating": 1650.0},
        "history": [
            {
                "attended": True,
                "rating": 1550.4,
                "ranking": 120,
                "contest": {"title": "Weekly Contest 200", "startTime": 1600000000},
            },
            {
                "attended": True,
                "rating": 1650.2,
                "ranking": 85,
                "contest": {"title": "Weekly Contest 201", "startTime": 1600604800},
            },
        ],
    })

    sync_service = CodeforcesSyncService(leetcode_adapter=mock_lc)
    stats = await sync_service.sync_link(link_id)

    # 3. Assertions
    assert stats["contests_synced"] == 2
    assert stats["submissions_synced"] == 0
    assert stats["problems_upserted"] == 0

    # 4. Verify in DB
    async with async_session_factory() as session:
        contests_res = await session.execute(
            select(ContestPerformance).where(
                ContestPerformance.user_id == user_id,
                ContestPerformance.platform == "leetcode",
            ).order_by(ContestPerformance.contest_date.asc())
        )
        contests = contests_res.scalars().all()
        assert len(contests) == 2
        assert contests[0].contest_name == "Weekly Contest 200"
        assert contests[0].rating_before == 1500
        assert contests[0].rating_after == 1550
        assert contests[1].rating_before == 1550
        assert contests[1].rating_after == 1650

        # Submissions should be 0
        subs_res = await session.execute(
            select(Submission).where(
                Submission.user_id == user_id,
                Submission.platform == "leetcode",
            )
        )
        assert len(subs_res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_leetcode_sync_with_cookie_and_verdict_normalization():
    """
    Verify with-cookie mode:
    Ingests submissions with normalized verdicts, upserts problems with difficulty_label and rating=None.
    """
    raw_cookie = "valid_session_cookie_xyz"
    encrypted_cookie = encrypt_token(raw_cookie)

    async with async_session_factory() as session:
        user = User(username=f"lc_user_cookie_{datetime.now().timestamp()}")
        session.add(user)
        await session.flush()

        link = PlatformLink(
            user_id=user.id,
            platform="leetcode",
            handle="test_lc_cookie_user",
            auth_token=encrypted_cookie,
            sync_status="idle",
        )
        session.add(link)
        await session.commit()
        user_id = user.id
        link_id = link.id

    mock_lc = LeetCodeAdapter()
    mock_lc.get_user_contest_ranking = AsyncMock(return_value={"ranking": None, "history": []})
    s1_slug = f"test-p1-{user_id}"
    s2_slug = f"test-p2-{user_id}"

    mock_lc.get_recent_submissions = AsyncMock(return_value=[
        {
            "id": "90001",
            "title": "Test Problem 1",
            "titleSlug": s1_slug,
            "timestamp": 1700000000,
            "raw_verdict": "Accepted",
            "verdict": "OK",
            "lang": "python3",
        },
        {
            "id": "90002",
            "title": "Test Problem 2",
            "titleSlug": s2_slug,
            "timestamp": 1700000100,
            "raw_verdict": "Wrong Answer",
            "verdict": "WRONG_ANSWER",
            "lang": "cpp",
        },
    ])

    async def mock_get_slug(slug):
        if slug == s1_slug:
            return {
                "questionFrontendId": "101",
                "title": "Test Problem 1",
                "titleSlug": s1_slug,
                "difficulty": "Easy",
                "topicTags": [{"name": "Array"}, {"name": "Hash Table"}],
            }
        else:
            return {
                "questionFrontendId": "102",
                "title": "Test Problem 2",
                "titleSlug": s2_slug,
                "difficulty": "Medium",
                "topicTags": [{"name": "Linked List"}, {"name": "Math"}],
            }

    mock_lc.get_problem_by_slug = AsyncMock(side_effect=mock_get_slug)

    sync_service = CodeforcesSyncService(leetcode_adapter=mock_lc)
    stats = await sync_service.sync_link(link_id)

    assert stats["submissions_synced"] == 2
    assert stats["problems_upserted"] == 2

    # Verify DB state
    async with async_session_factory() as session:
        # Check problems
        probs_res = await session.execute(
            select(Problem).where(Problem.platform == "leetcode", Problem.platform_id.in_([s1_slug, s2_slug]))
        )
        probs = {p.platform_id: p for p in probs_res.scalars().all()}
        assert s1_slug in probs
        assert probs[s1_slug].rating is None
        assert probs[s1_slug].difficulty_label == "Easy"
        assert "Array" in probs[s1_slug].tags

        assert s2_slug in probs
        assert probs[s2_slug].rating is None
        assert probs[s2_slug].difficulty_label == "Medium"

        # Check submissions
        subs_res = await session.execute(
            select(Submission).where(
                Submission.user_id == user_id,
                Submission.platform == "leetcode",
            ).order_by(Submission.platform_sub_id.asc())
        )
        subs = subs_res.scalars().all()
        assert len(subs) == 2
        assert subs[0].verdict == "OK"  # Normalized from "Accepted"
        assert subs[1].verdict == "WRONG_ANSWER"  # Normalized from "Wrong Answer"


@pytest.mark.asyncio
async def test_mixed_platform_analytics():
    """
    Verify analytics engine handles users with submissions across both Codeforces (numeric ratings)
    and LeetCode (difficulty_label, rating=None) without errors.
    """
    async with async_session_factory() as session:
        user = User(username=f"cross_platform_user_{datetime.now().timestamp()}")
        session.add(user)
        await session.flush()

        # CF problem (rated 1200)
        cf_prob = Problem(
            platform="codeforces",
            platform_id=f"cf_test_{user.id}",
            title="CF DP Problem",
            rating=1200,
            difficulty_label=None,
            tags=["dp"],
        )
        session.add(cf_prob)

        # LC problem (unrated, Easy)
        lc_prob = Problem(
            platform="leetcode",
            platform_id=f"lc_test_{user.id}",
            title="LC Easy Problem",
            rating=None,
            difficulty_label="Easy",
            tags=["dp", "array"],
        )
        session.add(lc_prob)
        await session.flush()

        # CF submission (OK)
        sub_cf = Submission(
            user_id=user.id,
            problem_id=cf_prob.id,
            platform="codeforces",
            platform_sub_id=888801,
            verdict="OK",
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(sub_cf)

        # LC submission (OK)
        sub_lc = Submission(
            user_id=user.id,
            problem_id=lc_prob.id,
            platform="leetcode",
            platform_sub_id=888802,
            verdict="OK",
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(sub_lc)
        await session.commit()
        user_id = user.id

    analytics_service = AnalyticsService()
    user_analytics = await analytics_service.recompute_user_analytics(user_id)

    assert user_analytics.total_problems_solved == 2
    assert user_analytics.total_submissions == 2
    # CF problem went to 1200-1399 bucket, LC problem went to unrated bucket
    assert user_analytics.difficulty_distribution.get("1200-1399", 0) >= 1
    assert user_analytics.difficulty_distribution.get("unrated", 0) >= 1
    # Both contributed to dp topic
    assert "dp" in user_analytics.topic_metrics
    assert user_analytics.topic_metrics["dp"]["sample_size"] == 2


@pytest.mark.asyncio
async def test_leetcode_sync_idempotency_and_lease():
    """
    Verify sync idempotency (repeated sync does not duplicate rows)
    and concurrency locking (active lease rejects concurrent sync with SyncAlreadyRunningError).
    """
    raw_cookie = "session_cookie_idempotency_test"
    encrypted_cookie = encrypt_token(raw_cookie)

    async with async_session_factory() as session:
        user = User(username=f"lc_idempotent_user_{datetime.now().timestamp()}")
        session.add(user)
        await session.flush()

        link = PlatformLink(
            user_id=user.id,
            platform="leetcode",
            handle="idempotent_lc_handle",
            auth_token=encrypted_cookie,
            sync_status="idle",
        )
        session.add(link)
        await session.commit()
        user_id = user.id
        link_id = link.id

    s_slug = f"idempotent-slug-{user_id}"
    mock_lc = LeetCodeAdapter()
    mock_lc.get_user_contest_ranking = AsyncMock(return_value={
        "ranking": None,
        "history": [
            {
                "attended": True,
                "rating": 1700.0,
                "ranking": 50,
                "contest": {"title": "Weekly Contest 300", "startTime": 1650000000},
            }
        ]
    })
    mock_lc.get_recent_submissions = AsyncMock(return_value=[
        {
            "id": "888001",
            "title": "Idempotent Problem",
            "titleSlug": s_slug,
            "timestamp": 1700005000,
            "raw_verdict": "Accepted",
            "verdict": "OK",
            "lang": "python3",
        }
    ])
    mock_lc.get_problem_by_slug = AsyncMock(return_value={
        "questionFrontendId": "300",
        "title": "Idempotent Problem",
        "titleSlug": s_slug,
        "difficulty": "Medium",
        "topicTags": [{"name": "Greedy"}],
    })

    sync_service = CodeforcesSyncService(leetcode_adapter=mock_lc)

    # 1. First sync run
    stats1 = await sync_service.sync_link(link_id)
    assert stats1["submissions_synced"] == 1
    assert stats1["contests_synced"] == 1

    # 2. Second sync run (idempotency check)
    stats2 = await sync_service.sync_link(link_id)
    assert stats2["submissions_synced"] == 0
    assert stats2["contests_synced"] == 0

    # Verify no duplicate rows in DB
    async with async_session_factory() as session:
        subs_res = await session.execute(
            select(Submission).where(
                Submission.user_id == user_id,
                Submission.platform == "leetcode",
            )
        )
        assert len(subs_res.scalars().all()) == 1

        contests_res = await session.execute(
            select(ContestPerformance).where(
                ContestPerformance.user_id == user_id,
                ContestPerformance.platform == "leetcode",
            )
        )
        assert len(contests_res.scalars().all()) == 1

    # 3. Concurrency lock check
    acquired = await sync_service.acquire_lease(link_id, worker_id="other_worker")
    assert acquired is True
    with pytest.raises(SyncAlreadyRunningError):
        await sync_service.sync_link(link_id)
    # Release manual test lease
    await sync_service.release_lease(link_id, worker_id="other_worker", status="idle")


@pytest.mark.asyncio
async def test_platform_link_api_with_auth_token():
    """
    Verify linking a platform via HTTP API with auth_token encrypts it in the DB.
    """
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.config import settings

    username = f"api_lc_user_{datetime.now().timestamp()}"
    headers = {"X-API-Key": settings.api_key}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        # Create user
        u_res = await ac.post("/api/users", json={"username": username})
        assert u_res.status_code == 201
        user_id = u_res.json()["id"]

        # Link LeetCode with auth_token
        secret_token = "my_super_secret_cookie_token_456"
        link_res = await ac.post(
            "/api/platforms/link",
            json={
                "user_id": user_id,
                "platform": "leetcode",
                "handle": "api_test_lc_handle",
                "auth_token": secret_token,
            }
        )
        assert link_res.status_code == 201
        link_id = link_res.json()["id"]

    # Verify directly in DB that auth_token is stored encrypted
    async with async_session_factory() as session:
        link_row = (await session.execute(
            select(PlatformLink).where(PlatformLink.id == link_id)
        )).scalar_one()

        assert link_row.auth_token is not None
        assert link_row.auth_token != secret_token
        assert "my_super_secret" not in link_row.auth_token
        assert decrypt_token(link_row.auth_token) == secret_token

