"""Unit tests for LLMClient abstraction and call logging."""

import pytest
from sqlalchemy import select
from app.database import async_session_factory, engine
from app.models.llm_call_log import LLMCallLog
from app.services.llm import LLMClient


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_mock_llm_client_generation_and_logging():
    client = LLMClient(provider="mock")

    system_prompt = "You are an FSM evaluator."
    user_prompt = "User said: I sorted the numbers."

    resp = await client.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        response_json=True,
        caller="fsm_evaluator",
        session_id=None,
    )

    assert resp.content is not None
    data = resp.json()
    assert "understood_current_level" in data
    assert resp.tokens_in > 0
    assert resp.tokens_out > 0
    assert resp.latency_ms >= 0

    # Verify that the call was logged in PostgreSQL llm_call_log table
    async with async_session_factory() as session:
        logs_res = await session.execute(
            select(LLMCallLog).where(LLMCallLog.caller == "fsm_evaluator").order_by(LLMCallLog.created_at.desc())
        )
        log_entry = logs_res.scalars().first()
        assert log_entry is not None
        assert log_entry.caller == "fsm_evaluator"
        assert log_entry.model == "mock-model"
        assert log_entry.prompt_hash is not None


@pytest.mark.asyncio
async def test_custom_mock_handler():
    client = LLMClient(provider="mock")
    client.register_mock_handler("custom_caller", lambda sys, usr: '{"custom": "success"}')

    resp = await client.generate(
        system_prompt="sys",
        user_prompt="usr",
        caller="custom_caller",
    )

    assert resp.json() == {"custom": "success"}
