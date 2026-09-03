"""Pydantic schemas for request and response validation in Phase 1."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


# ── Users ─────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime


# ── Platform Links ───────────────────────────────────────────────────
class PlatformLinkCreate(BaseModel):
    user_id: int
    platform: str = "codeforces"
    handle: str


class PlatformLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    platform: str
    handle: str
    last_synced_at: Optional[datetime] = None
    sync_status: str
    sync_error: Optional[str] = None
    created_at: datetime


class SyncTriggerResponse(BaseModel):
    status: str
    link_id: int
    submissions_synced: int
    contests_synced: int
    problems_upserted: int


# ── Submissions ───────────────────────────────────────────────────────
class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    problem_id: int
    platform: str
    platform_sub_id: int
    verdict: str
    language: Optional[str] = None
    submitted_at: datetime
    time_ms: Optional[int] = None
    memory_bytes: Optional[int] = None
    contest_id: Optional[int] = None
    participant_type: Optional[str] = None
    passed_test_count: Optional[int] = None


# ── Contest Performances ──────────────────────────────────────────────
class ContestPerformanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    platform: str
    contest_id: int
    contest_name: str
    rating_before: int
    rating_after: int
    rank: int
    contest_date: datetime


# ── Problems ──────────────────────────────────────────────────────────
class ProblemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    platform_id: str
    contest_id: Optional[int] = None
    problem_index: Optional[str] = None
    title: str
    rating: Optional[int] = None
    tags: Optional[List[str]] = None
    solved_count: int
    url: Optional[str] = None
