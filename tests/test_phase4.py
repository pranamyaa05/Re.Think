"""
Tests for Phase 4: Recommendations & Reflections.

Tests cover:
  - Edge case: user with zero confident topics -> insufficient_data
  - Edge case: topic with completion_rate < 0.50 -> study recommendation
  - Edge case: no unsolved candidates even after widening -> no_candidates
  - Recommender happy path (mocked analytics)
  - Reflector idempotency: second call returns existing, no new LLM call
  - Reflector skip: empty day -> skipped
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


# ── Recommender edge case tests ───────────────────────────────────────────────

class TestRecommender:
    """Unit tests for the deterministic recommendation engine."""

    def _make_analytics(self, topic_metrics: dict):
        """Create a mock UserAnalytics object."""
        mock = MagicMock()
        mock.topic_metrics = topic_metrics
        return mock

    @pytest.mark.asyncio
    async def test_insufficient_data_no_confident_topics(self):
        """User has no confident topics (all sample_size < 5) -> insufficient_data."""
        from app.services.recommender import get_next_problem_recommendation

        thin_metrics = {
            "dp": {
                "confident": False,
                "sample_size": 2,
                "demonstrated_level": 1200,
                "solve_completion_rate": 0.5,
            },
            "graphs": {
                "confident": True,
                "sample_size": 3,  # below MIN_CONFIDENT_SAMPLE=5
                "demonstrated_level": 1400,
                "solve_completion_rate": 0.7,
            },
        }
        mock_analytics = self._make_analytics(thin_metrics)

        with patch(
            "app.services.recommender._load_analytics",
            new=AsyncMock(return_value=mock_analytics),
        ):
            result = await get_next_problem_recommendation(user_id=999)

        assert result["status"] == "insufficient_data", f"Got: {result}"
        assert "insufficient" in result["reason"].lower() or "confident" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_insufficient_data_no_analytics(self):
        """User has no analytics row at all -> insufficient_data."""
        from app.services.recommender import get_next_problem_recommendation

        with patch(
            "app.services.recommender._load_analytics",
            new=AsyncMock(return_value=None),
        ):
            result = await get_next_problem_recommendation(user_id=9999)

        assert result["status"] == "insufficient_data"

    @pytest.mark.asyncio
    async def test_study_redirect_low_completion_rate(self):
        """Topic with completion_rate < 0.50 and >= 5 attempts -> study recommendation."""
        from app.services.recommender import get_next_problem_recommendation

        metrics = {
            "graphs": {
                "confident": True,
                "sample_size": 10,
                "demonstrated_level": 1400,
                "solve_completion_rate": 0.30,  # < 0.50 -> study redirect
                "low_confidence": False,
            },
        }
        mock_analytics = self._make_analytics(metrics)

        captured_recs = []

        class FakeSession:
            def add(self, obj):
                captured_recs.append(obj)
                obj.id = 42

            async def commit(self):
                pass

            async def execute(self, *a, **kw):
                r = MagicMock()
                r.scalar_one_or_none.return_value = mock_analytics
                return r

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        with patch("app.services.recommender.async_session_factory", return_value=FakeSession()):
            result = await get_next_problem_recommendation(user_id=999)

        assert result["status"] == "study", f"Got: {result}"
        assert result["topic"] == "graphs"
        assert "0.30" in result["reason"] or "30%" in result["reason"]

    @pytest.mark.asyncio
    async def test_no_candidates_after_widening(self):
        """No unsolved problems in range or widened range -> no_candidates."""
        from app.services.recommender import get_next_problem_recommendation

        metrics = {
            "dp": {
                "confident": True,
                "sample_size": 8,
                "demonstrated_level": 2800,
                "solve_completion_rate": 0.90,
                "low_confidence": False,
            },
        }
        mock_analytics = self._make_analytics(metrics)

        with patch(
            "app.services.recommender._load_analytics",
            new=AsyncMock(return_value=mock_analytics),
        ):
            with patch(
                "app.services.recommender._find_unsolved_problem",
                new=AsyncMock(return_value=None),
            ):
                result = await get_next_problem_recommendation(user_id=999)

        assert result["status"] == "no_candidates", f"Got: {result}"
        assert "dp" in result["topic"]
        assert "no unsolved" in result["reason"].lower() or "no candidate" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_weakest_topic_selection(self):
        """_find_weakest_confident_topic picks lowest completion_rate among confident topics."""
        from app.services.recommender import _find_weakest_confident_topic

        metrics = {
            "dp": {"confident": True, "sample_size": 10, "demonstrated_level": 1600, "solve_completion_rate": 0.90},
            "graphs": {"confident": True, "sample_size": 6, "demonstrated_level": 1400, "solve_completion_rate": 0.65},
            "greedy": {"confident": False, "sample_size": 10, "demonstrated_level": 1500, "solve_completion_rate": 0.20},
            "math": {"confident": True, "sample_size": 2, "demonstrated_level": 1800, "solve_completion_rate": 0.50},
        }

        topic, data = _find_weakest_confident_topic(metrics)
        # greedy is excluded (not confident), math is excluded (sample_size < 5)
        # graphs (0.65) < dp (0.90), so graphs should be picked
        assert topic == "graphs"
        assert data["solve_completion_rate"] == 0.65


# ── Reflector tests ───────────────────────────────────────────────────────────

class TestReflector:
    """Unit tests for the reflection generator."""

    @pytest.mark.asyncio
    async def test_skip_empty_day(self):
        """Day with zero submissions and zero hint sessions -> skipped, no LLM call."""
        from app.services.reflector import generate_daily_reflection

        target_date = date(2020, 1, 1)

        async def fake_existing(*a, **kw):
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        async def fake_empty_subs(*a, **kw):
            r = MagicMock()
            r.fetchall.return_value = []
            return r

        async def fake_zero_hs(*a, **kw):
            r = MagicMock()
            r.scalar.return_value = 0
            return r

        class FakeSession:
            async def execute(self, stmt, *a, **kw):
                stmt_str = str(stmt)
                if "hint_sessions" in stmt_str.lower():
                    return await fake_zero_hs()
                elif "reflections" in stmt_str.lower():
                    return await fake_existing()
                else:
                    return await fake_empty_subs()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=AssertionError("LLM should NOT be called"))

        with patch("app.services.reflector.async_session_factory", return_value=FakeSession()):
            result = await generate_daily_reflection(
                user_id=999, target_date=target_date, llm_client=mock_llm
            )

        assert result["status"] == "skipped"
        assert "no reflection generated" in result["reason"].lower() or "no submissions" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing(self):
        """Second call for same user/date returns existing without LLM call."""
        from app.services.reflector import generate_daily_reflection

        target_date = date(2026, 9, 20)
        fake_reflection = MagicMock()
        fake_reflection.id = 7
        fake_reflection.user_id = 45
        fake_reflection.date = target_date
        fake_reflection.content = "Great session today."
        fake_reflection.metrics = {"problems_attempted": 3}
        fake_reflection.generated_at = MagicMock()
        fake_reflection.generated_at.isoformat.return_value = "2026-09-20T10:00:00+00:00"

        async def fake_existing(*a, **kw):
            r = MagicMock()
            r.scalar_one_or_none.return_value = fake_reflection
            return r

        class FakeSession:
            async def execute(self, *a, **kw):
                return await fake_existing()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=AssertionError("LLM should NOT be called on second call"))

        with patch("app.services.reflector.async_session_factory", return_value=FakeSession()):
            result = await generate_daily_reflection(
                user_id=45, target_date=target_date, llm_client=mock_llm
            )

        assert result["status"] == "existing"
        assert result["reflection"]["content"] == "Great session today."
