"""
Submission model — individual problem submissions from Codeforces.

Field names verified against actual CF API response for user.status:
  id, contestId, creationTimeSeconds, relativeTimeSeconds,
  author.participantType, programmingLanguage, verdict,
  passedTestCount, timeConsumedMillis, memoryConsumedBytes

The unique constraint (user_id, platform, platform_sub_id) prevents
duplicate submissions during sync. ON CONFLICT DO NOTHING makes
re-syncing the same submissions safe (idempotent).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index(
            "uq_submission",
            "user_id", "platform", "platform_sub_id",
            unique=True,
        ),
        Index("ix_submissions_user_time", "user_id", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        ForeignKey("problems.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)

    # CF submission ID — BIGINT because CF IDs can exceed 2^31
    platform_sub_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # ── Fields from CF API ────────────────────────────────────────────────
    verdict: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. "OK", "WRONG_ANSWER", "TIME_LIMIT_EXCEEDED", "COMPILATION_ERROR"

    language: Mapped[Optional[str]] = mapped_column(String(80), default=None)
    # e.g. "C++23 (GCC 14-64, msys2)"

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # from creationTimeSeconds (Unix timestamp → datetime)

    time_ms: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    # from timeConsumedMillis — max execution time on any test

    memory_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, default=None)
    # from memoryConsumedBytes

    contest_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    # CF contestId — nullable for problems without a contest

    participant_type: Mapped[Optional[str]] = mapped_column(String(30), default=None)
    # from author.participantType: CONTESTANT, PRACTICE, VIRTUAL,
    # OUT_OF_COMPETITION, MANAGER

    relative_time_s: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    # from relativeTimeSeconds — seconds from contest start

    passed_test_count: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    # from passedTestCount — useful for "how close" analysis

    # Relationships
    user: Mapped["User"] = relationship(back_populates="submissions")
    problem: Mapped["Problem"] = relationship(back_populates="submissions")

    def __repr__(self) -> str:
        return (
            f"<Submission(id={self.id}, platform_sub_id={self.platform_sub_id}, "
            f"verdict='{self.verdict}')>"
        )
