"""
Tests for Phase 5A Closes:
1. Topic sorting in analytics handles None demonstrated_level safely when
   LeetCode problems (rating=NULL) are mixed into a topic with CF problems.
2. Recommender never recommends a NULL-rating (LeetCode) problem when
   filtering by numeric rating range.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy import select

from app.database import async_session_factory, engine
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.models.user_analytics import UserAnalytics
from app.services.analytics import AnalyticsService
from app.services.recommender import get_next_problem_recommendation


@pytest.fixture(autouse=True)
async def cleanup_db():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_analytics_mixed_rating_null_sorting_and_exclusion():
    """
    Close 1:
    Confirm topic sorting for strengths/weaknesses ranking by demonstrated_level
    handles None values safely when LeetCode problems (rating=NULL) are mixed
    into a topic with CF problems.
    None-level topics must be correctly excluded from strengths/weaknesses.
    """
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        user = User(username=f"mixed_sort_user_{datetime.now().timestamp()}")
        session.add(user)
        await session.flush()

        # Topic 1: "mixed_topic" has 1 CF solve (rating=1500) and 3 LeetCode solves (rating=None)
        # Total solves = 4, but rated solves = 1 (< 3 required for demonstrated_level)
        prob_cf = Problem(
            platform="codeforces",
            platform_id=f"cf_mix_{user.id}",
            title="CF Mix 1",
            rating=1500,
            difficulty_label=None,
            tags=["mixed_topic"],
        )
        session.add(prob_cf)

        lc_probs = []
        for i in range(3):
            p = Problem(
                platform="leetcode",
                platform_id=f"lc_mix_{user.id}_{i}",
                title=f"LC Mix {i}",
                rating=None,
                difficulty_label="Medium",
                tags=["mixed_topic"],
            )
            session.add(p)
            lc_probs.append(p)
        await session.flush()

        # Submissions for mixed_topic: all OK
        session.add(Submission(
            user_id=user.id, problem_id=prob_cf.id, platform="codeforces",
            platform_sub_id=10001, verdict="OK", submitted_at=now
        ))
        for i, lp in enumerate(lc_probs):
            session.add(Submission(
                user_id=user.id, problem_id=lp.id, platform="leetcode",
                platform_sub_id=10002 + i, verdict="OK", submitted_at=now
            ))

        # Topic 2: "confident_topic" has 5 CF solves (rating=1700) -> confident=True, demonstrated_level=1700
        for i in range(5):
            cp = Problem(
                platform="codeforces",
                platform_id=f"cf_conf_{user.id}_{i}",
                title=f"CF Conf {i}",
                rating=1700,
                difficulty_label=None,
                tags=["confident_topic"],
            )
            session.add(cp)
            await session.flush()
            session.add(Submission(
                user_id=user.id, problem_id=cp.id, platform="codeforces",
                platform_sub_id=20001 + i, verdict="OK", submitted_at=now
            ))

        await session.commit()
        user_id = user.id

    # Run analytics
    analytics_service = AnalyticsService()
    user_analytics = await analytics_service.recompute_user_analytics(user_id)

    # 1. Confirm topic metrics for mixed_topic
    mix_metrics = user_analytics.topic_metrics.get("mixed_topic")
    assert mix_metrics is not None, "mixed_topic must be in topic_metrics"
    assert mix_metrics["sample_size"] == 4, f"Expected 4 solves, got {mix_metrics['sample_size']}"
    assert mix_metrics["rated_sample_size"] == 1, f"Expected 1 rated solve, got {mix_metrics['rated_sample_size']}"
    assert mix_metrics["demonstrated_level"] is None, "demonstrated_level must be None when rated_count < 3"
    assert mix_metrics["confident"] is False, "confident must be False"

    # 2. Confirm topic metrics for confident_topic
    conf_metrics = user_analytics.topic_metrics.get("confident_topic")
    assert conf_metrics is not None
    assert conf_metrics["sample_size"] == 5
    assert conf_metrics["demonstrated_level"] == 1700
    assert conf_metrics["confident"] is True

    # 3. Confirm strengths:
    # "confident_topic" must be present; "mixed_topic" must be EXCLUDED because demonstrated_level is None
    assert "confident_topic" in user_analytics.strengths
    assert "mixed_topic" not in user_analytics.strengths, "mixed_topic (None level) must be excluded from strengths"

    # 4. Confirm weaknesses: sorting did not crash and mixed_topic is not falsely ranked
    assert isinstance(user_analytics.weaknesses, list)
    assert "mixed_topic" not in user_analytics.weaknesses


@pytest.mark.asyncio
async def test_recommender_never_selects_null_rating_leetcode_problem():
    """
    Close 2:
    Confirm get_next_problem_recommendation never recommends a NULL-rating
    (LeetCode) problem when the query filters by a CF-numeric rating range
    (e.g. demonstrated_level=1400 -> range [1400, 1600]).
    """
    now = datetime.now(timezone.utc)
    target_topic = f"geom_{int(datetime.now().timestamp())}"

    async with async_session_factory() as session:
        user = User(username=f"rec_null_user_{datetime.now().timestamp()}")
        session.add(user)
        await session.flush()
        user_id = user.id

        # Insert LeetCode problem with NULL rating, matching the target topic,
        # with high solved_count so it would be preferred if not filtered out
        lc_problem = Problem(
            platform="leetcode",
            platform_id=f"lc_geom_{user_id}",
            title="LeetCode Geometry Problem",
            rating=None,  # NULL rating
            difficulty_label="Medium",
            tags=[target_topic],
            solved_count=999999,  # Highest popularity
            url="https://leetcode.com/problems/geometry-problem/",
        )
        session.add(lc_problem)

        # Insert valid Codeforces problem with numeric rating in target range
        cf_problem = Problem(
            platform="codeforces",
            platform_id=f"cf_geom_{user_id}",
            title="Codeforces Geometry 1500",
            rating=1500,  # Matches target range [1400, 1600]
            difficulty_label=None,
            tags=[target_topic],
            solved_count=100,
            url="https://codeforces.com/contest/999/problem/A",
        )
        session.add(cf_problem)

        # Create 5 solves for target_topic so user has confident=True at demonstrated_level=1400
        for i in range(5):
            prob = Problem(
                platform="codeforces",
                platform_id=f"cf_solv_{user_id}_{i}",
                title=f"CF Solve {i}",
                rating=1400,
                difficulty_label=None,
                tags=[target_topic],
            )
            session.add(prob)
            await session.flush()
            session.add(Submission(
                user_id=user_id, problem_id=prob.id, platform="codeforces",
                platform_sub_id=30001 + i, verdict="OK", submitted_at=now
            ))

        await session.commit()

    # Recompute analytics so user has weakest confident topic = target_topic (demonstrated_level=1400)
    analytics_service = AnalyticsService()
    await analytics_service.recompute_user_analytics(user_id)

    # 1. Ask for recommendation: must select the CF problem (1500), NOT the LC problem (NULL)
    rec_result = await get_next_problem_recommendation(user_id)

    assert rec_result["status"] == "problem", f"Expected problem recommendation, got {rec_result}"
    assert rec_result["problem"]["rating"] == 1500
    assert rec_result["problem"]["platform"] == "codeforces"
    assert rec_result["problem"]["title"] == "Codeforces Geometry 1500"
    assert rec_result["problem"]["id"] != lc_problem.id

    # 2. Now mark the CF problem as solved by the user
    async with async_session_factory() as session:
        session.add(Submission(
            user_id=user_id, problem_id=cf_problem.id, platform="codeforces",
            platform_sub_id=39999, verdict="OK", submitted_at=now
        ))
        await session.commit()

    # 3. Call recommendation again: now ONLY the NULL-rating LC problem matches the topic
    # It must return status="no_candidates" and NEVER select the NULL-rating problem
    rec_result_2 = await get_next_problem_recommendation(user_id)

    assert rec_result_2["status"] == "no_candidates", (
        f"Expected 'no_candidates' since only NULL-rating problem exists, but got: {rec_result_2}"
    )
    assert rec_result_2["topic"] == target_topic
