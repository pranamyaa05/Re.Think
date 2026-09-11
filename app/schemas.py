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


# ── Phase 2 Analytics Schemas ─────────────────────────────────────────
class AnalyticsRecomputeResponse(BaseModel):
    status: str
    user_id: int
    computed_at: datetime
    total_problems_solved: int
    total_problems_attempted: int
    strengths: List[str]
    weaknesses: List[str]
    stale_topics: List[str]


class AnalyticsSummaryResponse(BaseModel):
    user_id: int
    computed_at: datetime
    total_problems_solved: int
    total_problems_attempted: int
    total_submissions: int
    overall_completion_rate: float
    overall_efficiency: float
    strengths: List[str]
    weaknesses: List[str]
    stale_topics: List[str]
    contest_summary: dict


class TopicAnalyticsResponse(BaseModel):
    tag: str
    demonstrated_level: Optional[int] = None
    freshness_days: Optional[int] = None
    sample_size: int
    rated_sample_size: int
    attempted_count: int
    confident: bool
    low_confidence: bool
    solve_completion_rate: float
    submission_efficiency: float
    avg_attempts_per_solve: float
    last_solved_at: Optional[str] = None


class DifficultyBucket(BaseModel):
    rating_range: str
    count: int


class DifficultyDistributionResponse(BaseModel):
    user_id: int
    buckets: List[DifficultyBucket]


class ContestMetricsResponse(BaseModel):
    user_id: int
    current_rating: Optional[int] = None
    max_rating: Optional[int] = None
    contest_count: int
    best_rank: Optional[int] = None
    avg_rank: Optional[float] = None
    avg_delta: Optional[float] = None
    rating_volatility: Optional[float] = None
    recent_contests: List[dict] = []


# ── Phase 3 Knowledge & Socratic Coach Schemas ───────────────────────
class KnowledgeExtractRequest(BaseModel):
    problem_id: int
    editorial_url: Optional[str] = None
    editorial_text: Optional[str] = None


class KnowledgeVerifyRequest(BaseModel):
    status: str  # user_verified | user_rejected


class ProblemKnowledgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: int
    source_type: str
    extraction_method: str
    validation_status: str
    approach_summary: Optional[str] = None
    key_insight: Optional[str] = None
    techniques: List[str] = []
    common_pitfalls: List[str] = []
    editorial_url: Optional[str] = None
    coach_mode: Optional[str] = None
    created_at: datetime


class SessionCreateRequest(BaseModel):
    user_id: int
    problem_id: int


class SessionMessageRequest(BaseModel):
    user_message: str
    current_code: Optional[str] = None
    request_escalation: bool = False


class HintMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    hint_level: Optional[int] = None
    content: str
    code_snapshot: Optional[str] = None
    leakage_checklist: Optional[dict] = None
    tier1_blocked: bool
    created_at: datetime


class HintSessionDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    problem_id: int
    current_level: int
    coach_mode: str
    user_stated_approach: Optional[str] = None
    outcome: str
    knowledge_confidence: Optional[str] = None
    started_at: datetime
    last_activity_at: datetime
    solved_at: Optional[datetime] = None
    messages: List[HintMessageResponse] = []


class SessionMessageResponse(BaseModel):
    coach_message: HintMessageResponse
    current_level: int
    coach_mode: str
    user_stated_approach: Optional[str] = None


class SessionConcludeRequest(BaseModel):
    outcome: str  # solved | gave_up

