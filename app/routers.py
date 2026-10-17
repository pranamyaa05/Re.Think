"""FastAPI route definitions for users, platform links, sync, submissions, contests, and problems."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.contest_performance import ContestPerformance
from app.models.hint_message import HintMessage
from app.models.hint_session import HintSession
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.models.submission import Submission
from app.models.user import User
from app.models.user_analytics import UserAnalytics
from app.schemas import (
    AnalyticsRecomputeResponse,
    AnalyticsSummaryResponse,
    ContestMetricsResponse,
    ContestPerformanceResponse,
    DifficultyBucket,
    DifficultyDistributionResponse,
    HintMessageResponse,
    HintSessionDetailResponse,
    KnowledgeExtractRequest,
    KnowledgeVerifyRequest,
    PlatformLinkCreate,
    PlatformLinkResponse,
    ProblemKnowledgeResponse,
    ProblemResponse,
    SessionConcludeRequest,
    SessionCreateRequest,
    SessionMessageRequest,
    SessionMessageResponse,
    SubmissionResponse,
    SyncTriggerResponse,
    TopicAnalyticsResponse,
    UserCreate,
    UserResponse,
)
from app.services.analytics import AnalyticsService
from app.dependencies.auth import verify_api_key
from app.services.coach import CoachService
from app.services.editorial import EditorialService, resolve_coach_mode
from app.services.sync import CodeforcesSyncService, SyncAlreadyRunningError
from app.utils.crypto import encrypt_token

router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


# ── Users ─────────────────────────────────────────────────────────────
@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.username == payload.username)
    res = await db.execute(query)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(username=payload.username)
    db.add(user)
    await db.flush()
    return user


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.id == user_id)
    res = await db.execute(query)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Platform Links ───────────────────────────────────────────────────
@router.post("/platforms/link", response_model=PlatformLinkResponse, status_code=status.HTTP_201_CREATED)
async def link_platform(payload: PlatformLinkCreate, db: AsyncSession = Depends(get_db)):
    user_q = select(User).where(User.id == payload.user_id)
    if not (await db.execute(user_q)).scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    existing_q = select(PlatformLink).where(
        PlatformLink.user_id == payload.user_id,
        PlatformLink.platform == payload.platform,
    )
    if (await db.execute(existing_q)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Platform '{payload.platform}' already linked for this user")

    handle = payload.handle
    if payload.platform == "leetcode" and payload.auth_token:
        try:
            from app.adapters.leetcode import LeetCodeAdapter
            lc_adapter = LeetCodeAdapter()
            auth_user = await lc_adapter.get_authenticated_user(payload.auth_token)
            if auth_user and auth_user.get("username"):
                handle = auth_user["username"]
        except Exception:
            pass

    link = PlatformLink(
        user_id=payload.user_id,
        platform=payload.platform,
        handle=handle,
        auth_token=encrypt_token(payload.auth_token) if payload.auth_token else None,
        sync_status="idle",
    )
    db.add(link)
    await db.flush()
    return link


@router.delete("/platforms/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_platform(link_id: int, db: AsyncSession = Depends(get_db)):
    query = select(PlatformLink).where(PlatformLink.id == link_id)
    link = (await db.execute(query)).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Platform link not found")
    await db.delete(link)
    return None


@router.get("/platforms/{link_id}/status", response_model=PlatformLinkResponse)
async def get_platform_status(link_id: int, db: AsyncSession = Depends(get_db)):
    query = select(PlatformLink).where(PlatformLink.id == link_id)
    link = (await db.execute(query)).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Platform link not found")
    return link


@router.post("/platforms/{link_id}/sync", response_model=SyncTriggerResponse)
async def trigger_platform_sync(link_id: int, force_full: bool = Query(False)):
    sync_service = CodeforcesSyncService()
    try:
        stats = await sync_service.sync_link(link_id, force_full=force_full)
        return SyncTriggerResponse(
            status="completed",
            link_id=link_id,
            submissions_synced=stats["submissions_synced"],
            contests_synced=stats["contests_synced"],
            problems_upserted=stats["problems_upserted"],
        )
    except SyncAlreadyRunningError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


# ── Submissions ───────────────────────────────────────────────────────
@router.get("/submissions", response_model=List[SubmissionResponse])
async def list_submissions(
    user_id: int = Query(...),
    verdict: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Submission).where(Submission.user_id == user_id)
    if verdict:
        stmt = stmt.where(Submission.verdict == verdict)
    stmt = stmt.order_by(Submission.submitted_at.desc()).offset(offset).limit(limit)

    res = await db.execute(stmt)
    return list(res.scalars().all())


# ── Contests ──────────────────────────────────────────────────────────
@router.get("/contests", response_model=List[ContestPerformanceResponse])
async def list_contests(
    user_id: int = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ContestPerformance)
        .where(ContestPerformance.user_id == user_id)
        .order_by(ContestPerformance.contest_date.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


# ── Problems ──────────────────────────────────────────────────────────
@router.get("/problems", response_model=List[ProblemResponse])
async def list_problems(
    tag: Optional[str] = Query(None),
    min_rating: Optional[int] = Query(None),
    max_rating: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Problem)
    if tag:
        # Utilize Postgres GIN array containment: ARRAY[tag] <@ tags
        stmt = stmt.where(Problem.tags.contains([tag]))
    if min_rating is not None:
        stmt = stmt.where(Problem.rating >= min_rating)
    if max_rating is not None:
        stmt = stmt.where(Problem.rating <= max_rating)

    stmt = stmt.order_by(Problem.id.asc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


# ── Analytics ─────────────────────────────────────────────────────────
@router.post("/analytics/{user_id}/recompute", response_model=AnalyticsRecomputeResponse)
async def recompute_analytics(user_id: int, db: AsyncSession = Depends(get_db)):
    user_res = await db.execute(select(User).where(User.id == user_id))
    if not user_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    analytics_service = AnalyticsService()
    record = await analytics_service.recompute_user_analytics(user_id)
    return AnalyticsRecomputeResponse(
        status="success",
        user_id=record.user_id,
        computed_at=record.computed_at,
        total_problems_solved=record.total_problems_solved,
        total_problems_attempted=record.total_problems_attempted,
        strengths=record.strengths,
        weaknesses=record.weaknesses,
        stale_topics=record.stale_topics,
    )


@router.get("/analytics/{user_id}/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(user_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(UserAnalytics).where(UserAnalytics.user_id == user_id))
    record = res.scalar_one_or_none()
    if not record:
        # Check user existence
        u_res = await db.execute(select(User).where(User.id == user_id))
        if not u_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")
        # Automatically compute if never computed
        analytics_service = AnalyticsService()
        record = await analytics_service.recompute_user_analytics(user_id)

    overall_completion = (
        round(record.total_problems_solved / record.total_problems_attempted, 4)
        if record.total_problems_attempted > 0 else 0.0
    )
    overall_efficiency = (
        round(record.total_problems_solved / record.total_submissions, 4)
        if record.total_submissions > 0 else 0.0
    )

    return AnalyticsSummaryResponse(
        user_id=record.user_id,
        computed_at=record.computed_at,
        total_problems_solved=record.total_problems_solved,
        total_problems_attempted=record.total_problems_attempted,
        total_submissions=record.total_submissions,
        overall_completion_rate=overall_completion,
        overall_efficiency=overall_efficiency,
        strengths=record.strengths,
        weaknesses=record.weaknesses,
        stale_topics=record.stale_topics,
        contest_summary=record.contest_metrics,
    )


@router.get("/analytics/{user_id}/topics", response_model=List[TopicAnalyticsResponse])
async def get_topic_analytics(
    user_id: int,
    min_samples: int = Query(1, ge=0),
    sort_by: str = Query("level", pattern="^(level|freshness|completion|name)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(UserAnalytics).where(UserAnalytics.user_id == user_id))
    record = res.scalar_one_or_none()
    if not record:
        u_res = await db.execute(select(User).where(User.id == user_id))
        if not u_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")
        analytics_service = AnalyticsService()
        record = await analytics_service.recompute_user_analytics(user_id)

    topic_dict = record.topic_metrics or {}
    items: List[TopicAnalyticsResponse] = []

    for tag, metrics in topic_dict.items():
        if metrics.get("sample_size", 0) >= min_samples:
            items.append(TopicAnalyticsResponse(tag=tag, **metrics))

    reverse = (order == "desc")
    if sort_by == "level":
        items.sort(key=lambda x: (x.demonstrated_level or 0, x.sample_size), reverse=reverse)
    elif sort_by == "freshness":
        items.sort(key=lambda x: (x.freshness_days if x.freshness_days is not None else 999999), reverse=reverse)
    elif sort_by == "completion":
        items.sort(key=lambda x: x.solve_completion_rate, reverse=reverse)
    elif sort_by == "name":
        items.sort(key=lambda x: x.tag, reverse=reverse)

    return items


@router.get("/analytics/{user_id}/difficulty", response_model=DifficultyDistributionResponse)
async def get_difficulty_distribution(user_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(UserAnalytics).where(UserAnalytics.user_id == user_id))
    record = res.scalar_one_or_none()
    if not record:
        u_res = await db.execute(select(User).where(User.id == user_id))
        if not u_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")
        analytics_service = AnalyticsService()
        record = await analytics_service.recompute_user_analytics(user_id)

    dist_map = record.difficulty_distribution or {}
    buckets = [
        DifficultyBucket(rating_range=k, count=v)
        for k, v in dist_map.items()
    ]
    return DifficultyDistributionResponse(user_id=user_id, buckets=buckets)


@router.get("/analytics/{user_id}/contests", response_model=ContestMetricsResponse)
async def get_contest_analytics(user_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(UserAnalytics).where(UserAnalytics.user_id == user_id))
    record = res.scalar_one_or_none()
    if not record:
        u_res = await db.execute(select(User).where(User.id == user_id))
        if not u_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")
        analytics_service = AnalyticsService()
        record = await analytics_service.recompute_user_analytics(user_id)

    cm = record.contest_metrics or {}
    return ContestMetricsResponse(
        user_id=user_id,
        current_rating=cm.get("current_rating"),
        max_rating=cm.get("max_rating"),
        contest_count=cm.get("contest_count", 0),
        best_rank=cm.get("best_rank"),
        avg_rank=cm.get("avg_rank"),
        avg_delta=cm.get("avg_delta"),
        rating_volatility=cm.get("rating_volatility"),
        recent_contests=cm.get("recent_contests", []),
    )


# ── Phase 3 Editorial Knowledge Endpoints ─────────────────────────────
@router.post("/knowledge/extract", response_model=ProblemKnowledgeResponse, status_code=status.HTTP_201_CREATED)
async def extract_problem_knowledge(payload: KnowledgeExtractRequest, db: AsyncSession = Depends(get_db)):
    prob_q = select(Problem).where(Problem.id == payload.problem_id)
    prob = (await db.execute(prob_q)).scalar_one_or_none()
    if not prob:
        raise HTTPException(status_code=404, detail=f"Problem id={payload.problem_id} not found")

    editorial_service = EditorialService()
    if payload.editorial_text:
        knowledge = await editorial_service.ingest_editorial(
            problem_id=payload.problem_id,
            raw_editorial=payload.editorial_text,
            editorial_url=payload.editorial_url,
        )
    elif payload.editorial_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(payload.editorial_url)
                r.raise_for_status()
                html_text = r.text
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch editorial from URL: {e}")

        knowledge = await editorial_service.ingest_editorial(
            problem_id=payload.problem_id,
            raw_editorial=html_text,
            editorial_url=payload.editorial_url,
        )
    else:
        knowledge = await editorial_service.generate_knowledge_fallback(payload.problem_id)

    coach_mode = resolve_coach_mode(knowledge)
    resp = ProblemKnowledgeResponse.model_validate(knowledge)
    resp.coach_mode = coach_mode
    return resp


@router.get("/knowledge/{problem_id}", response_model=ProblemKnowledgeResponse)
async def get_problem_knowledge(problem_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ProblemKnowledge).where(ProblemKnowledge.problem_id == problem_id))
    knowledge = res.scalar_one_or_none()
    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge record not found for this problem")

    coach_mode = resolve_coach_mode(knowledge)
    resp = ProblemKnowledgeResponse.model_validate(knowledge)
    resp.coach_mode = coach_mode
    return resp


@router.post("/knowledge/{id}/verify", response_model=ProblemKnowledgeResponse)
async def verify_problem_knowledge(id: int, payload: KnowledgeVerifyRequest, db: AsyncSession = Depends(get_db)):
    if payload.status not in ("user_verified", "user_rejected"):
        raise HTTPException(status_code=400, detail="Status must be 'user_verified' or 'user_rejected'")

    res = await db.execute(select(ProblemKnowledge).where(ProblemKnowledge.id == id))
    knowledge = res.scalar_one_or_none()
    if not knowledge:
        raise HTTPException(status_code=404, detail=f"ProblemKnowledge id={id} not found")

    knowledge.validation_status = payload.status
    await db.commit()

    coach_mode = resolve_coach_mode(knowledge)
    resp = ProblemKnowledgeResponse.model_validate(knowledge)
    resp.coach_mode = coach_mode
    return resp


# ── Phase 3 Socratic Coach Endpoints ─────────────────────────────────
@router.post("/coach/sessions", response_model=HintSessionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_coach_session(payload: SessionCreateRequest):
    coach_service = CoachService()
    try:
        session = await coach_service.create_session(
            user_id=payload.user_id,
            problem_id=payload.problem_id,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/coach/sessions/{session_id}", response_model=HintSessionDetailResponse)
async def get_coach_session(session_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(HintSession)
        .options(selectinload(HintSession.messages), selectinload(HintSession.problem))
        .where(HintSession.id == session_id)
    )
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail=f"HintSession id={session_id} not found")
    return session


@router.post("/coach/sessions/{session_id}/message", response_model=SessionMessageResponse)
async def send_coach_message(session_id: int, payload: SessionMessageRequest):
    coach_service = CoachService()
    try:
        coach_msg, updated_session = await coach_service.process_user_message(
            session_id=session_id,
            user_message=payload.user_message,
            current_code=payload.current_code,
            request_escalation=payload.request_escalation,
        )
        return SessionMessageResponse(
            coach_message=HintMessageResponse.model_validate(coach_msg),
            current_level=updated_session.current_level,
            coach_mode=updated_session.coach_mode,
            user_stated_approach=updated_session.user_stated_approach,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/coach/sessions/{session_id}/conclude", response_model=HintSessionDetailResponse)
async def conclude_coach_session(session_id: int, payload: SessionConcludeRequest):
    coach_service = CoachService()
    try:
        session = await coach_service.conclude_session(
            session_id=session_id,
            outcome=payload.outcome,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Phase 4: Recommendations ──────────────────────────────────────────────────

from app.services.recommender import (
    get_next_problem_recommendation,
    list_active_recommendations,
    dismiss_recommendation,
)
from app.schemas import (
    RecommendationResponse,
    RecommendationListItem,
    DismissResponse,
    ReflectionResponse,
)


@router.post("/recommendations/{user_id}/problem", response_model=RecommendationResponse)
async def generate_problem_recommendation(user_id: int, db: AsyncSession = Depends(get_db)):
    """Generate and persist a problem or study recommendation for the user."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    result = await get_next_problem_recommendation(user_id)
    return result


@router.get("/recommendations/{user_id}", response_model=List[RecommendationListItem])
async def get_active_recommendations(user_id: int, db: AsyncSession = Depends(get_db)):
    """List all active recommendations for the user."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await list_active_recommendations(user_id)


@router.post("/recommendations/{recommendation_id}/dismiss", response_model=DismissResponse)
async def dismiss_rec(recommendation_id: int):
    """Dismiss a recommendation by ID."""
    result = await dismiss_recommendation(recommendation_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return result


# ── Phase 4: Reflections ──────────────────────────────────────────────────────

from app.services.reflector import generate_daily_reflection, get_reflection
from datetime import date as date_type


@router.post("/reflections/{user_id}/generate", response_model=ReflectionResponse)
async def generate_reflection(
    user_id: int,
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, defaults to today"),
    db: AsyncSession = Depends(get_db),
):
    """Generate (or return existing) daily reflection for user_id on given date."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if date:
        try:
            target_date = date_type.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        target_date = date_type.today()

    result = await generate_daily_reflection(user_id=user_id, target_date=target_date)
    return result


@router.get("/reflections/{user_id}/{date}", response_model=ReflectionResponse)
async def get_reflection_by_date(
    user_id: int,
    date: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve an existing reflection for user_id on the given date."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        target_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    data = await get_reflection(user_id=user_id, target_date=target_date)
    if data is None:
        return {"status": "not_found", "reflection": None, "reason": f"No reflection for {date}"}
    return {"status": "existing", "reflection": data}

