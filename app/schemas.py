"""Pydantic schemas for request and response validation in Phase 1."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, computed_field, Field


# ── Users ─────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    external_id: Optional[str] = None


class UserResolveRequest(BaseModel):
    """OAuth identity to resolve to a backend user."""

    external_id: str
    username: Optional[str] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    external_id: str | None = None
    created_at: datetime


# ── Platform Links ───────────────────────────────────────────────────
class PlatformLinkCreate(BaseModel):
    user_id: int
    platform: str = "codeforces"
    handle: str
    auth_token: Optional[str] = None


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
    # Honest sync progress: fetched = what the platform API returned;
    # inserted/upserted = what was new to this database.
    submissions_fetched: int = 0
    submissions_inserted: int = 0
    contests_fetched: int = 0
    contests_inserted: int = 0
    problems_upserted: int = 0
    # False for LeetCode links without a session cookie (contests + aggregate
    # stats only; no per-submission data).
    submissions_available: bool = True

    @computed_field  # type: ignore[misc]
    @property
    def message(self) -> Optional[str]:
        """Human-readable message accompanying the status (e.g. why submissions
        are unavailable). Never contains the encrypted session cookie."""
        if self.platform == "leetcode" and not self.submissions_available:
            return (
                "Linked without a session cookie: contests and aggregate stats "
                "only; add a LEETCODE_SESSION cookie for per-submission data."
            )
        return None


class MeResponse(BaseModel):
    """The resolved current user together with their platform links and sync
    status — everything the UI needs to render the signed-in shell."""

    # populate_by_name lets the model be built either from the ORM attribute
    # ("platform_links") or directly by keyword ("links").
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    username: str
    external_id: Optional[str] = None
    created_at: datetime
    # Populated from the User.platform_links relationship; serialized as "links".
    links: List[PlatformLinkResponse] = Field(
        default=[], validation_alias="platform_links", serialization_alias="links"
    )


class CoachSessionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: int
    problem_title: Optional[str] = None
    current_level: int
    coach_mode: str
    outcome: str
    started_at: datetime
    last_activity_at: datetime


class ReflectionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: str
    content: str
    metrics: dict
    generated_at: Optional[datetime] = None


class SyncTriggerResponse(BaseModel):
    status: str
    link_id: int
    user_id: int
    # What the platform actually returned vs. what was new to this database.
    submissions_fetched: int
    submissions_newly_inserted: int
    contests_fetched: int
    contests_newly_inserted: int
    problems_upserted: int
    # Backwards-compatible aliases for the old "synced" counters, which meant
    # "newly inserted" and made a re-sync of existing data indistinguishable
    # from an empty/failed fetch.
    submissions_synced: int
    contests_synced: int


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
    difficulty_label: Optional[str] = None
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


# ── Phase 4: Recommendations ─────────────────────────────────────────────────

class ProblemSummary(BaseModel):
    id: int
    platform_id: str
    title: str
    rating: Optional[int] = None
    tags: List[str] = []
    url: Optional[str] = None


class RecommendationResponse(BaseModel):
    status: str  # 'problem' | 'study' | 'insufficient_data' | 'no_candidates'
    recommendation_id: Optional[int] = None
    topic: Optional[str] = None
    reason: Optional[str] = None
    problem: Optional[ProblemSummary] = None
    resource_url: Optional[str] = None


class RecommendationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_type: str
    topic: str
    reason: str
    status: str
    created_at: datetime
    target_rating_min: Optional[int] = None
    target_rating_max: Optional[int] = None
    problem: Optional[ProblemSummary] = None


class DismissResponse(BaseModel):
    status: str
    recommendation_id: Optional[int] = None


# ── Phase 4: Reflections ──────────────────────────────────────────────────────

class ReflectionData(BaseModel):
    id: int
    user_id: int
    date: str
    content: str
    metrics: dict
    generated_at: Optional[str] = None


class ReflectionResponse(BaseModel):
    status: str  # 'generated' | 'existing' | 'skipped'
    reflection: Optional[ReflectionData] = None
    reason: Optional[str] = None
