"""
ContestPerformance model — rating change and rank history from Codeforces.

Field names verified against actual CF API response for user.rating:
  contestId, contestName, rank, ratingUpdateTimeSeconds, oldRating, newRating

Unique constraint on (user_id, platform, contest_id) prevents duplicates.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ContestPerformance(Base):
    __tablename__ = "contest_performances"
    __table_args__ = (
        Index(
            "uq_contest_performance",
            "user_id", "platform", "contest_id",
            unique=True,
        ),
        Index("ix_contest_performances_user_date", "user_id", "contest_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)

    # ── Fields from CF API (user.rating) ──────────────────────────────────
    contest_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contest_name: Mapped[str] = mapped_column(String(500), nullable=False)
    rating_before: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_after: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    contest_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # from ratingUpdateTimeSeconds (Unix timestamp → datetime)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="contest_performances")

    def __repr__(self) -> str:
        return (
            f"<ContestPerformance(id={self.id}, contest_id={self.contest_id}, "
            f"rank={self.rank}, {self.rating_before}->{self.rating_after})>"
        )
