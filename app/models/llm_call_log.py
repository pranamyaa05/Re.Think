"""LLMCallLog model — tracks tokens, latency, prompt hashes, and session traceability."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LLMCallLog(Base):
    __tablename__ = "llm_call_log"
    __table_args__ = (
        Index("ix_llm_call_log_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hint_sessions.id", ondelete="SET NULL"), nullable=True
    )  # Traceability link to coaching session
    caller: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # editorial_extractor | fsm_evaluator | hint_generator | judge
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped[Optional["HintSession"]] = relationship(back_populates="llm_calls")

    def __repr__(self) -> str:
        return (
            f"<LLMCallLog(id={self.id}, caller='{self.caller}', model='{self.model}', "
            f"tokens_in={self.tokens_in}, tokens_out={self.tokens_out}, latency={self.latency_ms}ms)>"
        )
