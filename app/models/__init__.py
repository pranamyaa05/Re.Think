"""
SQLAlchemy ORM models — all imported here so Alembic can discover them
via a single import of `app.models`.
"""

from app.models.user import User
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.contest_performance import ContestPerformance

__all__ = [
    "User",
    "PlatformLink",
    "Problem",
    "Submission",
    "ContestPerformance",
]
