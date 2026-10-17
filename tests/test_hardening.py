"""
Tests for Deployment Hardening:
- Part 1: API Key authentication (missing, wrong, correct, /health bypass)
- Part 2: Rate limiter & daily LLM call cap
- Part 4: Error handling and exception shielding
- Part 5: CORS preflight headers
- Part 7: Health & readiness probe
"""

import uuid
import pytest
from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import async_session_factory, engine
from app.main import app
from app.models.hint_session import HintSession
from app.models.llm_call_log import LLMCallLog
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.models.user import User
from app.services.coach import reset_rate_limits


@pytest.fixture(autouse=True)
async def cleanup():
    reset_rate_limits()
    yield
    reset_rate_limits()
    await engine.dispose()


# ── Part 1: Authentication Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_no_header_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/users/1")
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid or missing API key"}


@pytest.mark.asyncio
async def test_auth_wrong_key_returns_401():
    headers = {"X-API-Key": "totally-wrong-key-value"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        res = await ac.get("/api/users/1")
    assert res.status_code == 401
    assert res.json() == {"detail": "Invalid or missing API key"}


@pytest.mark.asyncio
async def test_auth_correct_key_returns_success():
    username = f"auth_user_{uuid.uuid4().hex[:6]}"
    headers = {"X-API-Key": settings.api_key}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        res = await ac.post("/api/users", json={"username": username})
    assert res.status_code == 201
    assert res.json()["username"] == username


@pytest.mark.asyncio
async def test_health_accessible_without_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
    assert res.json()["database"] == "connected"


# ── Part 2: Rate Limiting & Daily LLM Call Guards ─────────────────────────────

@pytest.mark.asyncio
async def test_coach_message_rate_limiting():
    """Two coach messages within 1s for same user triggers 429."""
    # Seed user, problem, knowledge, session
    async with async_session_factory() as session:
        user = User(username=f"rl_user_{uuid.uuid4().hex[:6]}")
        session.add(user)
        prob = Problem(
            platform="codeforces",
            platform_id=f"7777_{uuid.uuid4().hex[:4]}",
            title="Rate Limit Problem",
            rating=1500,
        )
        session.add(prob)
        await session.commit()

        know = ProblemKnowledge(
            problem_id=prob.id,
            source_type="official_editorial",
            extraction_method="heading_match",
            validation_status="unchecked",
            approach_summary="Greedy approach",
            key_insight="Sort elements first",
        )
        session.add(know)

        hs = HintSession(
            user_id=user.id,
            problem_id=prob.id,
            current_level=1,
            coach_mode="socratic_nudge",
            outcome="ongoing",
        )
        session.add(hs)
        await session.commit()
        session_id = hs.id

    reset_rate_limits()
    headers = {"X-API-Key": settings.api_key}

    from unittest.mock import patch, AsyncMock
    from app.services.llm import LLMResponse

    async def mock_generate(*args, **kwargs):
        caller = kwargs.get("caller", "")
        if caller == "fsm_evaluator":
            return LLMResponse(content='{"progress_verdict": "on_track", "target_level": 1, "reasoning": "User has good idea"}', tokens_in=50, tokens_out=20)
        return LLMResponse(content="What if you sort the array first?", tokens_in=50, tokens_out=15)

    with patch("app.services.llm.LLMClient.generate", side_effect=mock_generate):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
            # First message
            res1 = await ac.post(
                f"/api/coach/sessions/{session_id}/message",
                json={"user_message": "Here is my first thought on the problem."},
            )
            assert res1.status_code == 200

            # Second message immediately (within 1 second)
            res2 = await ac.post(
                f"/api/coach/sessions/{session_id}/message",
                json={"user_message": "Rapid fire second message without waiting."},
            )
            assert res2.status_code == 429
            data = res2.json()
            assert "Rate limit exceeded" in data["detail"]
            assert "Retry-After" in res2.headers


@pytest.mark.asyncio
async def test_daily_llm_call_cap_blocks_and_no_new_log_row():
    """When daily LLM call cap is exceeded, returns 429 and creates NO new llm_call_log row."""
    async with async_session_factory() as session:
        user = User(username=f"cap_user_{uuid.uuid4().hex[:6]}")
        session.add(user)
        prob = Problem(
            platform="codeforces",
            platform_id=f"6666_{uuid.uuid4().hex[:4]}",
            title="Cap Problem",
            rating=1400,
        )
        session.add(prob)
        await session.commit()

        hs = HintSession(
            user_id=user.id,
            problem_id=prob.id,
            current_level=1,
            coach_mode="socratic_nudge",
            outcome="ongoing",
        )
        session.add(hs)
        await session.commit()
        user_id = user.id
        session_id = hs.id

        # Insert dummy LLMCallLog rows for today to exceed settings.daily_llm_call_cap
        now_utc = datetime.now(timezone.utc)
        cap = settings.daily_llm_call_cap
        for i in range(cap + 5):
            log = LLMCallLog(
                session_id=session_id,
                caller="test_filler",
                model="test-model",
                prompt_hash="dummy_hash",
                tokens_in=10,
                tokens_out=10,
                latency_ms=10,
                created_at=now_utc,
            )
            session.add(log)
        await session.commit()

        # Count total log rows before call
        from sqlalchemy import text
        count_before = (await session.execute(
            text("SELECT COUNT(*) FROM llm_call_log WHERE session_id=:sid"),
            {"sid": session_id},
        )).scalar()

    reset_rate_limits()
    headers = {"X-API-Key": settings.api_key}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        res = await ac.post(
            f"/api/coach/sessions/{session_id}/message",
            json={"user_message": "Trying to call coach when cap is already exceeded."},
        )
        assert res.status_code == 429
        data = res.json()
        assert f"Daily LLM call cap of {cap} calls exceeded" in data["detail"]

    # Verify NO new row was added to llm_call_log
    async with async_session_factory() as session:
        count_after = (await session.execute(
            text("SELECT COUNT(*) FROM llm_call_log WHERE session_id=:sid"),
            {"sid": session_id},
        )).scalar()

    assert count_after == count_before, f"Expected {count_before} rows, but got {count_after} (new row was leaked!)"


# ── Part 4: Error Handling Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unhandled_exception_returns_clean_500_when_debug_false():
    """With debug=False, unhandled exceptions return generic 500 without internal tracebacks."""
    # Temporarily force debug=False
    original_debug = settings.debug
    settings.debug = False

    # Trigger a 500 by passing an endpoint that raises an unhandled internal exception
    # e.g., register a temporary broken route or simulate via router
    from fastapi import APIRouter
    test_router = APIRouter()

    @test_router.get("/test/broken-route")
    async def broken_route():
        raise RuntimeError("Secret internal database password or SQL query failure: SELECT * FROM secrets")

    app.include_router(test_router)

    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as ac:
            res = await ac.get("/test/broken-route")
        assert res.status_code == 500
        assert res.json() == {"error": "internal_server_error"}
        assert "Secret" not in res.text
        assert "traceback" not in res.text.lower()
    finally:
        settings.debug = original_debug


# ── Part 5: CORS Headers Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cors_preflight_headers():
    """OPTIONS preflight from an allowed origin returns CORS headers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.options(
            "/api/users",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key,Content-Type",
            },
        )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert res.headers.get("access-control-allow-credentials") == "true"
    assert "POST" in res.headers.get("access-control-allow-methods", "")
