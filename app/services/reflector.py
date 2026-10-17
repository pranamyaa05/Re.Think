"""
Reflection Generator — LLM-powered daily reflections.

Design:
  - Idempotent: returns existing reflection for (user_id, date) without re-calling LLM.
  - Skips silently if zero submissions AND zero hint_sessions that day.
  - Pulls only real DB data for the prompt — no invented details.
  - Persists to `reflections` with raw metrics JSONB for cross-checking.
  - caller="reflector" in llm_call_log for traceability.
"""

import logging
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, func, cast, Date
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session_factory
from app.models.hint_session import HintSession
from app.models.problem import Problem
from app.models.reflection import Reflection
from app.models.submission import Submission
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)

REFLECTION_SYSTEM_PROMPT = """You are a concise, honest competitive programming coach writing a daily reflection for a student.
Write exactly 3-4 sentences. Be specific about what was actually practiced. Avoid generic platitudes.

STRICT GROUNDING RULES:
- You may ONLY reference problem names, submission counts, solve counts, topics, and hint usage that are explicitly listed in the provided data below.
- Do NOT infer, speculate about, or name any detail (problem names, strategies, debugging patterns, code issues) that is not directly stated in the data.
- If the data says "0 solved out of N attempted", you may note the low solve rate but must NOT guess WHY (e.g. do not claim "stuck in a debugging loop" unless the data explicitly says so).
- Base your "pattern" observation strictly on the per-problem breakdown provided. For example, if one problem has far more submissions than others, you may note that.
- Your recommendation for tomorrow must be generic enough to not require information you were not given.

Do NOT use bullet points."""

REFLECTION_USER_PROMPT_TEMPLATE = """Write a daily reflection for {date}.

Today's activity:
- Distinct problems attempted: {problems_attempted}
- Distinct problems solved: {problems_solved}
- Total submissions: {total_submissions}
- Topics practiced: {topics}
- Hint sessions used: {hints_used}

Per-problem breakdown (name | submissions | solved):
{per_problem_breakdown}

Write 3-4 grounded sentences based ONLY on the data above."""


async def generate_daily_reflection(
    user_id: int,
    target_date: date,
    llm_client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """
    Generate (or return existing) daily reflection for user on target_date.

    Returns dict with:
      status: 'existing' | 'generated' | 'skipped'
      reflection: {...} if status in ('existing', 'generated')
      reason: str if status='skipped'
    """
    async with async_session_factory() as session:
        # ── 1. Idempotency: return existing if present ─────────────────────────
        existing = await session.execute(
            select(Reflection).where(
                Reflection.user_id == user_id,
                Reflection.date == target_date,
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is not None:
            return {
                "status": "existing",
                "reflection": _serialize(existing_row),
            }

        # ── 2. Pull real data for target_date ─────────────────────────────────
        date_start = datetime(
            target_date.year, target_date.month, target_date.day, 0, 0, 0,
            tzinfo=timezone.utc
        )
        date_end = date_start + timedelta(days=1)

        # Submissions that day
        sub_rows = (await session.execute(
            select(Submission.problem_id, Submission.verdict)
            .where(
                Submission.user_id == user_id,
                Submission.submitted_at >= date_start,
                Submission.submitted_at < date_end,
            )
        )).fetchall()

        # Hint sessions touched that day (created or last_activity_at)
        hs_rows = (await session.execute(
            select(func.count(HintSession.id))
            .where(
                HintSession.user_id == user_id,
                HintSession.last_activity_at >= date_start,
                HintSession.last_activity_at < date_end,
            )
        )).scalar()

        problems_attempted_ids = {r[0] for r in sub_rows}
        problems_solved_ids = {r[0] for r in sub_rows if r[1] == "OK"}
        hints_used = hs_rows or 0
        total_submissions = len(sub_rows)

        # ── 3. Skip if nothing happened ────────────────────────────────────────
        if not problems_attempted_ids and hints_used == 0:
            return {
                "status": "skipped",
                "reason": (
                    f"No submissions or hint sessions found for user {user_id} on {target_date}. "
                    "No reflection generated."
                ),
            }

        # ── 4. Build per-problem breakdown with real counts ────────────────────
        topics_set: set = set()
        per_problem_lines: List[str] = []

        if problems_attempted_ids:
            # Count submissions per problem_id
            sub_counts: Counter = Counter()
            solve_flags: Dict[int, bool] = {}
            for pid, verdict in sub_rows:
                sub_counts[pid] += 1
                if verdict == "OK":
                    solve_flags[pid] = True
                elif pid not in solve_flags:
                    solve_flags[pid] = False

            # Fetch titles and tags for attempted problems
            prob_rows = (await session.execute(
                select(Problem.id, Problem.title, Problem.tags)
                .where(Problem.id.in_(problems_attempted_ids))
            )).fetchall()

            prob_lookup: Dict[int, Tuple[str, list]] = {}
            for pid, title, tags in prob_rows:
                prob_lookup[pid] = (title, tags or [])
                if tags:
                    topics_set.update(tags)

            # Build per-problem breakdown lines, sorted by submission count desc
            for pid, count in sub_counts.most_common():
                title, _ = prob_lookup.get(pid, (f"problem_{pid}", []))
                solved_str = "yes" if solve_flags.get(pid, False) else "no"
                per_problem_lines.append(
                    f"  {title} | {count} submissions | solved: {solved_str}"
                )

        topics_list = sorted(topics_set)[:8]  # cap at 8 for prompt clarity

        per_problem_breakdown = (
            "\n".join(per_problem_lines[:10])  # cap at 10 problems in prompt
            if per_problem_lines
            else "  (no problems attempted)"
        )

        metrics = {
            "problems_attempted": len(problems_attempted_ids),
            "problems_solved": len(problems_solved_ids),
            "total_submissions": total_submissions,
            "hints_used": hints_used,
            "topics": topics_list,
        }

        # ── 5. Build LLM prompt from real data only ────────────────────────────
        user_prompt = REFLECTION_USER_PROMPT_TEMPLATE.format(
            date=str(target_date),
            problems_attempted=metrics["problems_attempted"],
            problems_solved=metrics["problems_solved"],
            total_submissions=total_submissions,
            topics=", ".join(topics_list) if topics_list else "various",
            hints_used=hints_used,
            per_problem_breakdown=per_problem_breakdown,
        )

        # ── 6. Call LLM ────────────────────────────────────────────────────────
        if llm_client is None:
            llm_client = LLMClient()

        response = await llm_client.generate(
            system_prompt=REFLECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            caller="reflector",
            session_id=None,
        )
        content = response.content.strip()

        # ── 7. Persist reflection (idempotent insert) ──────────────────────────
        reflection = Reflection(
            user_id=user_id,
            date=target_date,
            content=content,
            metrics=metrics,
        )
        session.add(reflection)
        await session.commit()

        return {
            "status": "generated",
            "reflection": _serialize(reflection),
        }


async def get_reflection(user_id: int, target_date: date) -> Optional[Dict[str, Any]]:
    """Return an existing reflection or None."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Reflection).where(
                Reflection.user_id == user_id,
                Reflection.date == target_date,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _serialize(row)


def _serialize(r: Reflection) -> Dict[str, Any]:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "date": str(r.date),
        "content": r.content,
        "metrics": r.metrics,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
    }
