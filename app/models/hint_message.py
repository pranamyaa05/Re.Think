"""HintMessage model — individual messages with code state and guardrail checklists."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HintMessage(Base):
    __tablename__ = "hint_messages"
    __table_args__ = (
        Index("ix_hint_messages_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("hint_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | coach
    hint_level: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # NULL for user messages, 0-4 for coach
    content: Mapped[str] = mapped_column(Text, nullable=False)
    code_snapshot: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # User's code snapshot at time of message
    leakage_checklist: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )  # Tier 2 binary checklist
    tier1_blocked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["HintSession"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<HintMessage(id={self.id}, session_id={self.session_id}, role='{self.role}', "
            f"level={self.hint_level}, blocked={self.tier1_blocked})>"
        )
