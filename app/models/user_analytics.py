"""
UserAnalytics model — materialized caching layer for Phase 2 analytics.

Stores precomputed topic demonstrated proficiency (median ratings + freshness),
behavioral metrics (solve completion rate + pre-AC submission efficiency),
difficulty distributions, contest performance metrics, and diagnostic classifications
(strengths, weaknesses, stale topics).
"""

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserAnalytics(Base):
    __tablename__ = "user_analytics"
    __table_args__ = (
        Index("ix_user_analytics_user_id", "user_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # ── Summary counts ───────────────────────────────────────────────────
    total_problems_solved: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    total_problems_attempted: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    total_submissions: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )

    # ── Detailed Metric Payloads (JSONB) ──────────────────────────────────
    # Topic breakdown: tag -> {demonstrated_level, freshness_days, sample_size,
    #                          confident, low_confidence, solve_completion_rate,
    #                          submission_efficiency, avg_attempts_per_solve, last_solved_at}
    topic_metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", default=dict, nullable=False
    )

    # Rating distribution: {"800-999": count, "1000-1199": count, ...}
    difficulty_distribution: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", default=dict, nullable=False
    )

    # Contest analytics: {current_rating, max_rating, contest_count, best_rank, avg_rank, volatility}
    contest_metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", default=dict, nullable=False
    )

    # ── Diagnostic Tag Classifications ────────────────────────────────────
    strengths: Mapped[List[str]] = mapped_column(
        ARRAY(String), server_default="{}", default=list, nullable=False
    )
    weaknesses: Mapped[List[str]] = mapped_column(
        ARRAY(String), server_default="{}", default=list, nullable=False
    )
    stale_topics: Mapped[List[str]] = mapped_column(
        ARRAY(String), server_default="{}", default=list, nullable=False
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship back to User
    user: Mapped["User"] = relationship(back_populates="analytics")

    def __repr__(self) -> str:
        return (
            f"<UserAnalytics(user_id={self.user_id}, "
            f"solved={self.total_problems_solved}, "
            f"computed_at='{self.computed_at}')>"
        )
