"""
SQLAlchemy ORM models — all imported here so Alembic can discover them
via a single import of `app.models`.
"""

from app.models.user import User
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.contest_performance import ContestPerformance
from app.models.user_analytics import UserAnalytics
from app.models.problem_knowledge import ProblemKnowledge
from app.models.hint_session import HintSession
from app.models.hint_message import HintMessage
from app.models.llm_call_log import LLMCallLog

__all__ = [
    "User",
    "PlatformLink",
    "Problem",
    "Submission",
    "ContestPerformance",
    "UserAnalytics",
    "ProblemKnowledge",
    "HintSession",
    "HintMessage",
    "LLMCallLog",
]
