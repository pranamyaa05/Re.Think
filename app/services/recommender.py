"""
Recommendation Engine — pure, deterministic rule-based logic.

Design:
  - Reads user_analytics.topic_metrics to find the weakest CONFIDENT topic
    (sample_size >= 5, demonstrated_level exists, confident=True).
  - If solve_completion_rate < 0.50 with >= 5 attempts → study recommendation.
  - Otherwise → find an unsolved problem in [demonstrated_level, demonstrated_level+200],
    widen to [demonstrated_level-100, demonstrated_level+300] if empty.
  - Persists every recommendation to the `recommendations` table.
  - No LLM calls — all logic is deterministic.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, not_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.problem import Problem
from app.models.recommendation import Recommendation
from app.models.submission import Submission
from app.models.user_analytics import UserAnalytics

logger = logging.getLogger(__name__)

# ── Static resource lookup for common CF tags ──────────────────────────────────
STUDY_RESOURCES: Dict[str, str] = {
    "dp": "https://codeforces.com/blog/entry/67003",
    "graphs": "https://codeforces.com/blog/entry/68138",
    "greedy": "https://codeforces.com/blog/entry/90033",
    "math": "https://codeforces.com/blog/entry/77284",
    "binary search": "https://codeforces.com/blog/entry/9901",
    "two pointers": "https://codeforces.com/blog/entry/91124",
    "trees": "https://codeforces.com/blog/entry/18051",
    "strings": "https://codeforces.com/blog/entry/54200",
    "number theory": "https://codeforces.com/blog/entry/62352",
    "combinatorics": "https://codeforces.com/blog/entry/62356",
    "data structures": "https://codeforces.com/blog/entry/15729",
    "dfs and similar": "https://codeforces.com/blog/entry/68138",
    "sortings": "https://codeforces.com/blog/entry/68138",
    "bitmasks": "https://codeforces.com/blog/entry/18051",
    "dsu": "https://cp-algorithms.com/data_structures/disjoint_set_union.html",
    "segment tree": "https://cp-algorithms.com/data_structures/segment_tree.html",
    "flows": "https://cp-algorithms.com/graph/edmonds_karp.html",
    "geometry": "https://cp-algorithms.com/geometry/basic-geometry.html",
    "brute force": "https://codeforces.com/blog/entry/68138",
    "constructive algorithms": "https://codeforces.com/blog/entry/68138",
    "implementation": "https://codeforces.com/blog/entry/68138",
    "games": "https://codeforces.com/blog/entry/17921",
    "probabilities": "https://codeforces.com/blog/entry/62356",
}
DEFAULT_RESOURCE = "https://codeforces.com/problemset"

MIN_CONFIDENT_SAMPLE = 5


# ── Public interface ─────────────────────────────────────────────────────────


async def get_next_problem_recommendation(user_id: int) -> Dict[str, Any]:
    """
    Generate and persist a recommendation for the given user.

    Returns a dict with keys:
      status: 'problem' | 'study' | 'insufficient_data' | 'no_candidates'
      recommendation_id: int (if persisted)
      topic, reason, problem (if type='problem'), resource_url (if type='study')
    """
    async with async_session_factory() as session:
        # ── 1. Load analytics ─────────────────────────────────────────────────
        analytics = await _load_analytics(session, user_id)
        if analytics is None:
            return {
                "status": "insufficient_data",
                "reason": (
                    f"No analytics found for user {user_id}. "
                    "Sync submissions and recompute analytics first."
                ),
            }

        topic_metrics: Dict[str, Any] = analytics.topic_metrics or {}

        # ── 2. Find weakest confident topic ───────────────────────────────────
        weakest_topic, topic_data = _find_weakest_confident_topic(topic_metrics)

        if weakest_topic is None:
            return {
                "status": "insufficient_data",
                "reason": (
                    "No confident topics found (need at least 5 rated solved problems "
                    "per topic). Keep practicing to build a reliable skill profile."
                ),
            }

        demonstrated_level: int = topic_data["demonstrated_level"]
        completion_rate: float = topic_data.get("solve_completion_rate", 1.0)
        sample_size: int = topic_data.get("sample_size", 0)

        # ── 3. Study redirect if completion_rate < 0.50 ───────────────────────
        if completion_rate < 0.50 and sample_size >= MIN_CONFIDENT_SAMPLE:
            return await get_study_recommendation(user_id, weakest_topic, topic_data, session)

        # ── 4. Find unsolved problem ──────────────────────────────────────────
        rating_min = demonstrated_level
        rating_max = demonstrated_level + 200

        problem = await _find_unsolved_problem(
            session, user_id, weakest_topic, rating_min, rating_max
        )

        # Widen range once if empty
        if problem is None:
            rating_min = demonstrated_level - 100
            rating_max = demonstrated_level + 300
            problem = await _find_unsolved_problem(
                session, user_id, weakest_topic, rating_min, rating_max
            )

        if problem is None:
            return {
                "status": "no_candidates",
                "topic": weakest_topic,
                "reason": (
                    f"Your weakest confident topic is '{weakest_topic}' "
                    f"(demonstrated level {demonstrated_level}, "
                    f"completion rate {completion_rate:.0%} over {sample_size} attempts). "
                    f"No unsolved problems found in ratings "
                    f"[{demonstrated_level - 100}, {demonstrated_level + 300}] for this topic."
                ),
            }

        # ── 5. Persist recommendation ─────────────────────────────────────────
        reason = (
            f"Your demonstrated level in '{weakest_topic}' is {demonstrated_level} "
            f"with {completion_rate:.0%} completion rate over {sample_size} attempts. "
            f"This problem is rated {problem.rating} "
            f"(target range [{rating_min}, {rating_max}])."
        )

        rec = Recommendation(
            user_id=user_id,
            recommendation_type="problem",
            problem_id=problem.id,
            topic=weakest_topic,
            reason=reason,
            target_rating_min=rating_min,
            target_rating_max=rating_max,
            status="active",
        )
        session.add(rec)
        await session.commit()

        return {
            "status": "problem",
            "recommendation_id": rec.id,
            "topic": weakest_topic,
            "reason": reason,
            "problem": {
                "id": problem.id,
                "platform": problem.platform,
                "platform_id": problem.platform_id,
                "title": problem.title,
                "rating": problem.rating,
                "difficulty_label": problem.difficulty_label,
                "tags": problem.tags or [],
                "url": problem.url,
            },
        }


async def get_study_recommendation(
    user_id: int,
    topic: str,
    topic_data: Optional[Dict[str, Any]] = None,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Persist and return a study-type recommendation for the given topic.
    Can be called standalone or as a redirect from get_next_problem_recommendation.
    """
    own_session = session is None
    if own_session:
        session = async_session_factory()
        await session.__aenter__()

    try:
        if topic_data is None:
            # Load analytics to get topic data
            analytics = await _load_analytics(session, user_id)
            if analytics is None:
                return {
                    "status": "insufficient_data",
                    "reason": f"No analytics for user {user_id}.",
                }
            topic_data = (analytics.topic_metrics or {}).get(topic, {})

        completion_rate = topic_data.get("solve_completion_rate", 0.0)
        sample_size = topic_data.get("sample_size", 0)
        resource_url = STUDY_RESOURCES.get(topic, DEFAULT_RESOURCE)

        reason = (
            f"Your completion rate for '{topic}' is {completion_rate:.0%} "
            f"over {sample_size} attempts (threshold: 50%). "
            f"Focus on studying fundamentals before attempting harder problems. "
            f"Resource: {resource_url}"
        )

        rec = Recommendation(
            user_id=user_id,
            recommendation_type="study",
            problem_id=None,
            topic=topic,
            reason=reason,
            target_rating_min=None,
            target_rating_max=None,
            status="active",
        )
        session.add(rec)
        await session.commit()

        return {
            "status": "study",
            "recommendation_id": rec.id,
            "topic": topic,
            "reason": reason,
            "resource_url": resource_url,
        }
    finally:
        if own_session:
            await session.__aexit__(None, None, None)


async def list_active_recommendations(user_id: int) -> List[Dict[str, Any]]:
    """Return all active recommendations for the user, newest first."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Recommendation)
            .where(
                Recommendation.user_id == user_id,
                Recommendation.status == "active",
            )
            .order_by(Recommendation.created_at.desc())
        )
        recs = result.scalars().all()

        out = []
        for r in recs:
            item: Dict[str, Any] = {
                "id": r.id,
                "recommendation_type": r.recommendation_type,
                "topic": r.topic,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "target_rating_min": r.target_rating_min,
                "target_rating_max": r.target_rating_max,
            }
            if r.problem_id:
                prob_res = await session.get(Problem, r.problem_id)
                if prob_res:
                    item["problem"] = {
                        "id": prob_res.id,
                        "platform_id": prob_res.platform_id,
                        "title": prob_res.title,
                        "rating": prob_res.rating,
                        "tags": prob_res.tags or [],
                        "url": prob_res.url,
                    }
            out.append(item)
        return out


async def dismiss_recommendation(recommendation_id: int) -> Dict[str, Any]:
    """Set a recommendation's status to 'dismissed'."""
    async with async_session_factory() as session:
        rec = await session.get(Recommendation, recommendation_id)
        if rec is None:
            return {"status": "not_found"}
        rec.status = "dismissed"
        await session.commit()
        return {"status": "dismissed", "recommendation_id": recommendation_id}


# ── Private helpers ───────────────────────────────────────────────────────────


async def _load_analytics(
    session: AsyncSession, user_id: int
) -> Optional[UserAnalytics]:
    result = await session.execute(
        select(UserAnalytics).where(UserAnalytics.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _find_weakest_confident_topic(
    topic_metrics: Dict[str, Any]
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Pick the weakest confident topic:
      - confident=True
      - sample_size >= MIN_CONFIDENT_SAMPLE (5)
      - demonstrated_level exists
    Sort by solve_completion_rate ASC (lower = weaker), break ties by demonstrated_level DESC.
    """
    candidates = []
    for topic, data in topic_metrics.items():
        if (
            data.get("confident", False)
            and data.get("sample_size", 0) >= MIN_CONFIDENT_SAMPLE
            and data.get("demonstrated_level") is not None
        ):
            candidates.append((topic, data))

    if not candidates:
        return None, None

    # Sort: lowest completion rate first, then highest level first (harder weaknesses rank first)
    candidates.sort(
        key=lambda x: (
            x[1].get("solve_completion_rate", 1.0),
            -x[1].get("demonstrated_level", 0),
        )
    )
    return candidates[0]


async def _find_unsolved_problem(
    session: AsyncSession,
    user_id: int,
    topic: str,
    rating_min: int,
    rating_max: int,
) -> Optional[Problem]:
    """
    Find one unsolved problem for the user in the given topic and rating range.
    Anti-join against submissions with verdict='OK'.
    Ordered by solved_count DESC (well-known problems first).
    """
    solved_subq = (
        select(Submission.problem_id)
        .where(
            Submission.user_id == user_id,
            Submission.verdict == "OK",
        )
        .scalar_subquery()
    )

    stmt = (
        select(Problem)
        .where(
            Problem.tags.contains([topic]),
            Problem.rating >= rating_min,
            Problem.rating <= rating_max,
            Problem.id.not_in(solved_subq),
        )
        .order_by(Problem.solved_count.desc())
        .limit(1)
    )

    result = await session.execute(stmt)
    return result.scalar_one_or_none()
