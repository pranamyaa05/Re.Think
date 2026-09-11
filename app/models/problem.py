"""
Problem model — competitive programming problems from Codeforces.

Field names match the actual CF API response (verified against live data):
  problem.contestId, problem.index, problem.name, problem.rating, problem.tags

platform_id is a synthetic unique key: f"{contestId}_{index}" (e.g. "1930_C")
because CF has no single problem identifier.
"""

from typing import Optional

from sqlalchemy import Index, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (
        Index("ix_problems_platform_id", "platform", "platform_id", unique=True),
        Index("ix_problems_tags_gin", "tags", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)

    # Synthetic unique ID: "{contestId}_{index}" for CF
    platform_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # CF-specific fields (from the API's Problem object)
    contest_id: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    problem_index: Mapped[Optional[str]] = mapped_column(String(10), default=None)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    tags: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String), server_default="{}", default=list
    )
    solved_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    url: Mapped[Optional[str]] = mapped_column(String(500), default=None)

    # Relationships
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )
    knowledge: Mapped[list["ProblemKnowledge"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )
    hint_sessions: Mapped[list["HintSession"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Problem(id={self.id}, platform='{self.platform}', "
            f"title='{self.title}', rating={self.rating})>"
        )
