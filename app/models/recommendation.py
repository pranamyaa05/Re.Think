"""Recommendation model — stores generated recommendations for users."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_user_id", "user_id"),
        Index("ix_recommendations_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recommendation_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'problem' | 'study'
    problem_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("problems.id", ondelete="SET NULL"), nullable=True
    )  # null if type='study'
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    target_rating_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_rating_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), server_default="active", default="active", nullable=False
    )  # active | completed | dismissed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="recommendations")
    problem: Mapped[Optional["Problem"]] = relationship(back_populates="recommendations")

    def __repr__(self) -> str:
        return (
            f"<Recommendation(id={self.id}, user_id={self.user_id}, "
            f"type='{self.recommendation_type}', topic='{self.topic}', status='{self.status}')>"
        )
