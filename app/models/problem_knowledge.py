"""ProblemKnowledge model — extracted editorial and solution guidance."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProblemKnowledge(Base):
    __tablename__ = "problem_knowledge"
    __table_args__ = (
        UniqueConstraint("problem_id", "source_type", name="uq_problem_knowledge_problem_source"),
        Index("ix_problem_knowledge_problem_id", "problem_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    problem_id: Mapped[int] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # official_editorial | llm_generated | user_contributed
    extraction_method: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # heading_match | llm_parsed | manual
    validation_status: Mapped[str] = mapped_column(
        String(30), server_default="unchecked", default="unchecked", nullable=False
    )  # unchecked | format_ok | user_verified | user_rejected
    approach_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_insight: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    techniques: Mapped[List[str]] = mapped_column(
        ARRAY(String), server_default="{}", default=list, nullable=False
    )
    common_pitfalls: Mapped[List[str]] = mapped_column(
        ARRAY(String), server_default="{}", default=list, nullable=False
    )
    editorial_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    problem: Mapped["Problem"] = relationship(back_populates="knowledge")

    def __repr__(self) -> str:
        return (
            f"<ProblemKnowledge(problem_id={self.problem_id}, source='{self.source_type}', "
            f"method='{self.extraction_method}', status='{self.validation_status}')>"
        )
