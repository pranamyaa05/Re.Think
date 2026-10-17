"""Reflection model — stores daily generated reflections for users."""

from datetime import date, datetime
from typing import Any, Dict

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Reflection(Base):
    __tablename__ = "reflections"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_reflection_user_date"),
        Index("ix_reflections_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", default=dict, nullable=False
    )  # problems_attempted, problems_solved, hints_used, topics list
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["User"] = relationship(back_populates="reflections")

    def __repr__(self) -> str:
        return f"<Reflection(id={self.id}, user_id={self.user_id}, date='{self.date}')>"
