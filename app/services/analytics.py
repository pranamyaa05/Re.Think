"""
Analytics Service — transforms raw submission, problem, and contest data into
interpretable proficiency, behavioral, and diagnostic metrics.

Key rules implemented:
1. Pre-AC Cutoff: Submissions are only counted up to the first AC timestamp per problem.
2. Demonstrated Level: Median (P50) of solved ratings. Gated by >=5 confident, 3-4 low confidence, <3 None.
3. Freshness: Days elapsed since the most recent solve in a topic.
4. Completion Rate: Solved unique problems / attempted unique problems.
5. Weakness Threshold: At least 5 attempts required before flagging a topic for low completion rate.
6. Contest Volatility: Standard deviation of contest rating deltas.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.contest_performance import ContestPerformance
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user_analytics import UserAnalytics


def calculate_median(values: List[int]) -> Optional[int]:
    """Calculates integer median of a list of integers."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    else:
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) // 2


def get_rating_bucket(rating: Optional[int]) -> str:
    """Classifies a problem rating into standardized histogram buckets."""
    if rating is None:
        return "unrated"
    if rating < 1000:
        return "800-999"
    elif rating < 1200:
        return "1000-1199"
    elif rating < 1400:
        return "1200-1399"
    elif rating < 1600:
        return "1400-1599"
    elif rating < 1800:
        return "1600-1799"
    elif rating < 2000:
        return "1800-1999"
    elif rating < 2200:
        return "2000-2199"
    elif rating < 2400:
        return "2200-2399"
    else:
        return "2400+"


class ProblemSummary:
    """Aggregated stats for a single problem attempted by a user."""
    def __init__(self, problem: Problem):
        self.problem_id = problem.id
        self.rating = problem.rating
        self.tags = problem.tags or []
        self.is_solved = False
        self.first_ac_time: Optional[datetime] = None
        self.attempts_to_solve = 0
        self.total_submissions = 0


class AnalyticsService:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or async_session_factory

    async def recompute_user_analytics(self, user_id: int) -> UserAnalytics:
        """
        Extracts user submissions, problems, and contests, computes all metrics,
        and saves them idempotently into user_analytics.
        """
        async with self.session_factory() as session:
            # 1. Fetch all submissions ordered chronologically
            sub_stmt = (
                select(Submission, Problem)
                .join(Problem, Submission.problem_id == Problem.id)
                .where(Submission.user_id == user_id)
                .order_by(Submission.submitted_at.asc())
            )
            sub_res = await session.execute(sub_stmt)
            submission_rows = sub_res.all()

            # 2. Fetch all contest performances ordered by date
            contest_stmt = (
                select(ContestPerformance)
                .where(ContestPerformance.user_id == user_id)
                .order_by(ContestPerformance.contest_date.asc())
            )
            contest_res = await session.execute(contest_stmt)
            contest_rows = list(contest_res.scalars().all())

        # Process metrics in memory (safe and fast, no held DB connection)
        analytics_payload = self._compute_metrics(submission_rows, contest_rows)

        # 3. Persist into user_analytics using ON CONFLICT DO UPDATE
        async with self.session_factory() as session:
            stmt = insert(UserAnalytics).values(
                user_id=user_id,
                total_problems_solved=analytics_payload["total_problems_solved"],
                total_problems_attempted=analytics_payload["total_problems_attempted"],
                total_submissions=analytics_payload["total_submissions"],
                topic_metrics=analytics_payload["topic_metrics"],
                difficulty_distribution=analytics_payload["difficulty_distribution"],
                contest_metrics=analytics_payload["contest_metrics"],
                strengths=analytics_payload["strengths"],
                weaknesses=analytics_payload["weaknesses"],
                stale_topics=analytics_payload["stale_topics"],
                computed_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "total_problems_solved": stmt.excluded.total_problems_solved,
                    "total_problems_attempted": stmt.excluded.total_problems_attempted,
                    "total_submissions": stmt.excluded.total_submissions,
                    "topic_metrics": stmt.excluded.topic_metrics,
                    "difficulty_distribution": stmt.excluded.difficulty_distribution,
                    "contest_metrics": stmt.excluded.contest_metrics,
                    "strengths": stmt.excluded.strengths,
                    "weaknesses": stmt.excluded.weaknesses,
                    "stale_topics": stmt.excluded.stale_topics,
                    "computed_at": stmt.excluded.computed_at,
                },
            )
            await session.execute(stmt)
            await session.commit()

            # Return freshly saved record
            res = await session.execute(
                select(UserAnalytics).where(UserAnalytics.user_id == user_id)
            )
            return res.scalar_one()

    def _compute_metrics(
        self,
        submission_rows: List[Tuple[Submission, Problem]],
        contests: List[ContestPerformance],
    ) -> Dict[str, Any]:
        """Pure calculation function for testing and evaluation."""
        now_utc = datetime.now(timezone.utc)

        # ── Step A: Group submissions by problem with pre-AC cutoff ─────────
        problem_map: Dict[int, ProblemSummary] = {}
        # Group submissions list per problem_id
        subs_by_prob: Dict[int, List[Submission]] = {}
        for sub, prob in submission_rows:
            if prob.id not in problem_map:
                problem_map[prob.id] = ProblemSummary(prob)
                subs_by_prob[prob.id] = []
            subs_by_prob[prob.id].append(sub)

        total_submissions_count = len(submission_rows)

        for prob_id, summary in problem_map.items():
            subs = subs_by_prob[prob_id]
            summary.total_submissions = len(subs)

            # Find earliest AC
            ac_times = [s.submitted_at for s in subs if s.verdict == "OK"]
            if ac_times:
                summary.is_solved = True
                first_ac = min(ac_times)
                summary.first_ac_time = first_ac
                # Only count submissions up to and including the first AC
                summary.attempts_to_solve = sum(
                    1 for s in subs if s.submitted_at <= first_ac
                )
            else:
                summary.is_solved = False
                summary.first_ac_time = None
                summary.attempts_to_solve = len(subs)

        all_problems = list(problem_map.values())
        solved_problems = [p for p in all_problems if p.is_solved]

        total_problems_attempted = len(all_problems)
        total_problems_solved = len(solved_problems)

        # ── Step B: Difficulty Distribution ─────────────────────────────────
        bucket_counts: Dict[str, int] = {
            "800-999": 0,
            "1000-1199": 0,
            "1200-1399": 0,
            "1400-1599": 0,
            "1600-1799": 0,
            "1800-1999": 0,
            "2000-2199": 0,
            "2200-2399": 0,
            "2400+": 0,
            "unrated": 0,
        }
        for sp in solved_problems:
            b = get_rating_bucket(sp.rating)
            bucket_counts[b] = bucket_counts.get(b, 0) + 1

        # ── Step C: Per-Topic Aggregation & WEAM Metrics ─────────────────────
        # Topic -> list of ProblemSummary
        topic_attempted: Dict[str, List[ProblemSummary]] = {}
        for p in all_problems:
            for tag in p.tags:
                if tag not in topic_attempted:
                    topic_attempted[tag] = []
                topic_attempted[tag].append(p)

        topic_metrics: Dict[str, Any] = {}
        for tag, probs in topic_attempted.items():
            attempted_count = len(probs)
            solved_in_topic = [p for p in probs if p.is_solved]
            solved_count = len(solved_in_topic)

            # Solved ratings for demonstrated level
            solved_ratings = [p.rating for p in solved_in_topic if p.rating is not None]
            rated_count = len(solved_ratings)

            # Demonstrated level & confidence gating
            if rated_count >= 3:
                demonstrated_level = calculate_median(solved_ratings)
                confident = (rated_count >= 5)
                low_confidence = (3 <= rated_count < 5)
            else:
                demonstrated_level = None
                confident = False
                low_confidence = False

            # Freshness (days since last solve)
            if solved_in_topic:
                latest_solve = max(p.first_ac_time for p in solved_in_topic if p.first_ac_time)
                freshness_days = max(0, (now_utc - latest_solve).days)
                last_solved_at = latest_solve.isoformat()
            else:
                freshness_days = None
                last_solved_at = None

            # Completion rate
            completion_rate = round(solved_count / attempted_count, 4) if attempted_count > 0 else 0.0

            # Submission efficiency with pre-AC cutoff
            sum_pre_ac_attempts = sum(p.attempts_to_solve for p in probs)
            submission_efficiency = (
                round(solved_count / sum_pre_ac_attempts, 4)
                if sum_pre_ac_attempts > 0 else 0.0
            )

            # Average attempts per solved problem
            sum_solved_attempts = sum(p.attempts_to_solve for p in solved_in_topic)
            avg_attempts = (
                round(sum_solved_attempts / solved_count, 2)
                if solved_count > 0 else 0.0
            )

            topic_metrics[tag] = {
                "demonstrated_level": demonstrated_level,
                "freshness_days": freshness_days,
                "sample_size": solved_count,
                "rated_sample_size": rated_count,
                "attempted_count": attempted_count,
                "confident": confident,
                "low_confidence": low_confidence,
                "solve_completion_rate": completion_rate,
                "submission_efficiency": submission_efficiency,
                "avg_attempts_per_solve": avg_attempts,
                "last_solved_at": last_solved_at,
            }

        # ── Step D: Contest Metrics ──────────────────────────────────────────
        contest_metrics: Dict[str, Any] = {}
        if contests:
            current_rating = contests[-1].rating_after
            max_rating = max(c.rating_after for c in contests)
            best_rank = min(c.rank for c in contests)
            avg_rank = round(sum(c.rank for c in contests) / len(contests), 1)
            deltas = [c.rating_after - c.rating_before for c in contests]
            avg_delta = round(sum(deltas) / len(deltas), 1)

            # Population standard deviation for volatility
            var = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas)
            volatility = round(math.sqrt(var), 1)

            recent_history = [
                {
                    "contest_id": c.contest_id,
                    "contest_name": c.contest_name,
                    "rank": c.rank,
                    "rating_before": c.rating_before,
                    "rating_after": c.rating_after,
                    "delta": c.rating_after - c.rating_before,
                    "date": c.contest_date.isoformat(),
                }
                for c in contests[-10:]
            ]

            contest_metrics = {
                "current_rating": current_rating,
                "max_rating": max_rating,
                "contest_count": len(contests),
                "best_rank": best_rank,
                "avg_rank": avg_rank,
                "avg_delta": avg_delta,
                "rating_volatility": volatility,
                "recent_contests": recent_history,
            }
        else:
            contest_metrics = {
                "current_rating": None,
                "max_rating": None,
                "contest_count": 0,
                "best_rank": None,
                "avg_rank": None,
                "avg_delta": None,
                "rating_volatility": None,
                "recent_contests": [],
            }

        # ── Step E: Diagnostics (Strengths, Weaknesses, Stale) ───────────────
        confident_topics = [
            (tag, data) for tag, data in topic_metrics.items()
            if data["confident"] and data["demonstrated_level"] is not None
        ]

        # 1. Strengths: Top confident topics by demonstrated_level
        sorted_by_level = sorted(
            confident_topics, key=lambda x: x[1]["demonstrated_level"], reverse=True
        )
        strengths = [tag for tag, _ in sorted_by_level[:5]]

        # 2. Weaknesses:
        # Rule a: Low completion rate (< 50%) with AT LEAST 5 attempts (Approved Fix #2)
        # Rule b: In the bottom 25% of demonstrated level among confident topics (if >= 4 exist)
        weakness_candidates: Set[str] = set()

        for tag, data in topic_metrics.items():
            if data["attempted_count"] >= 5 and data["solve_completion_rate"] < 0.50:
                weakness_candidates.add(tag)

        if len(confident_topics) >= 4:
            cutoff_idx = max(1, len(confident_topics) // 4)
            # Reverse sorted, so bottom 25% is at the tail
            bottom_topics = sorted_by_level[-cutoff_idx:]
            for tag, _ in bottom_topics:
                # Only if not already in strengths
                if tag not in strengths:
                    weakness_candidates.add(tag)

        # Sort weaknesses by completion rate ascending
        weaknesses = sorted(
            list(weakness_candidates),
            key=lambda t: (topic_metrics[t]["solve_completion_rate"], topic_metrics[t]["demonstrated_level"] or 0)
        )[:5]

        # 3. Stale Topics:
        # Topics where demonstrated_level >= user's overall median level, but freshness > 60 days
        stale_topics: List[str] = []
        if confident_topics:
            all_demonstrated = [data["demonstrated_level"] for _, data in confident_topics]
            median_level = calculate_median(all_demonstrated) or 0

            for tag, data in confident_topics:
                if (
                    data["demonstrated_level"] >= median_level
                    and data["freshness_days"] is not None
                    and data["freshness_days"] > 60
                ):
                    stale_topics.append(tag)

            # Sort stale topics by freshness_days descending
            stale_topics = sorted(
                stale_topics,
                key=lambda t: topic_metrics[t]["freshness_days"] or 0,
                reverse=True
            )[:5]

        return {
            "total_problems_solved": total_problems_solved,
            "total_problems_attempted": total_problems_attempted,
            "total_submissions": total_submissions_count,
            "topic_metrics": topic_metrics,
            "difficulty_distribution": bucket_counts,
            "contest_metrics": contest_metrics,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "stale_topics": stale_topics,
        }
