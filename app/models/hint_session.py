"""HintSession model — tracks multi-turn Socratic coaching sessions."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HintSession(Base):
    __tablename__ = "hint_sessions"
    __table_args__ = (
        Index("ix_hint_sessions_user_problem", "user_id", "problem_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    current_level: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )  # 0 to 4
    coach_mode: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # full_coach | cautious_coach | peer_mode
    user_stated_approach: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(20), server_default="ongoing", default="ongoing", nullable=False
    )  # ongoing | solved | gave_up | expired
    knowledge_confidence: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # mirrors coach_mode at session start
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    solved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="hint_sessions")
    problem: Mapped["Problem"] = relationship(back_populates="hint_sessions")
    messages: Mapped[List["HintMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="HintMessage.created_at.asc()",
    )
    llm_calls: Mapped[List["LLMCallLog"]] = relationship(back_populates="session")

    def __repr__(self) -> str:
        return (
            f"<HintSession(id={self.id}, user_id={self.user_id}, problem_id={self.problem_id}, "
            f"level={self.current_level}, mode='{self.coach_mode}', outcome='{self.outcome}')>"
        )
