"""FastAPI route definitions for users, platform links, sync, submissions, contests, and problems."""

import logging
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.contest_performance import ContestPerformance
from app.models.hint_message import HintMessage
from app.models.hint_session import HintSession
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.models.recommendation import Recommendation
from app.models.reflection import Reflection
from app.models.submission import Submission
from app.models.user import User
from app.models.user_analytics import UserAnalytics
from app.schemas import (
    AnalyticsRecomputeResponse,
    AnalyticsSummaryResponse,
    CoachSessionListItem,
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
    ReflectionListItem,
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
    UserResolveRequest,
    UserResponse,
    MeResponse,
)
from app.services.analytics import AnalyticsService
from app.dependencies.auth import (
    assert_link_owner,
    get_verified_identity,
    require_user_scope,
    verify_api_key,
)
from app.services.coach import CoachService
from app.services.editorial import EditorialService, resolve_coach_mode
from app.services.sync import CodeforcesSyncService, SyncAlreadyRunningError
from app.utils.crypto import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


async def run_link_sync(link_id: int) -> None:
    """Background entrypoint: sync one link and record failures on the link row.

    ``CodeforcesSyncService.sync_link`` acquires the lease, writes
    ``sync_status='failed'`` plus the verbatim error on failure, and rebuilds
    analytics on success, so this wrapper only has to keep the task alive.
    """
    sync_service = CodeforcesSyncService()
    try:
        await sync_service.sync_link(link_id)
    except SyncAlreadyRunningError:
        logger.info("Background sync for link %s skipped: lease already held", link_id)
    except Exception:
        logger.exception("Background sync failed for link %s", link_id)


# ── Users ─────────────────────────────────────────────────────────────
@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.username == payload.username)
    res = await db.execute(query)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(username=payload.username, external_id=payload.external_id)
    db.add(user)
    await db.flush()
    return user

async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.id == user_id)
    res = await db.execute(query)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/users/me", response_model=UserResponse)
async def get_current_user(
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    """Return the backend user mapped to the verified OAuth identity."""
    res = await db.execute(select(User).where(User.external_id == external_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Identity is not mapped to a backend user; call /users/resolve first",
        )
    return user


@router.get("/me", response_model=MeResponse)
async def get_me(
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    """Return the resolved backend user with their platform links and sync status.

    The identity comes from the verified X-External-Id header (forwarded by the
    frontend server), never from a browser-supplied user id.
    """
    res = await db.execute(
        select(User)
        .where(User.external_id == external_id)
        .options(selectinload(User.platform_links))
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Identity is not mapped to a backend user; call /users/resolve first",
        )
    return MeResponse.model_validate(user)


@router.post("/users/resolve", response_model=UserResponse)
async def resolve_user_by_external_id(
    payload: UserResolveRequest,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a user by their external OAuth identity (idempotent).

    Returns the existing backend user mapped to this external_id, or creates
    one if none exists. The body identity must match the verified header, so
    a server-side caller cannot resolve an identity it does not represent.
    """
    if payload.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="external_id does not match the verified identity",
        )

    query = select(User).where(User.external_id == external_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if user:
        return user

    username = (payload.username or "").strip() or f"oauth_{external_id}"
    user = User(username=username, external_id=external_id)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Concurrent resolve (or a username collision): roll back the failed
        # insert and return the row the winner created.
        await db.rollback()
        user = (await db.execute(query)).scalar_one_or_none()
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{username}' is already taken; retry with a different username",
        )
    return user


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_endpoint(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
    user = await get_user(user_id, db)
    return user

# ── Platform Links ───────────────────────────────────────────────────
@router.post("/platforms/link", response_model=PlatformLinkResponse, status_code=status.HTTP_201_CREATED)
async def link_platform(
    payload: PlatformLinkCreate,
    background_tasks: BackgroundTasks,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    user_q = select(User).where(User.id == payload.user_id)
    user = (await db.execute(user_q)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this user",
        )

    existing_q = select(PlatformLink).where(
        PlatformLink.user_id == payload.user_id,
        PlatformLink.platform == payload.platform,
    )
    if (await db.execute(existing_q)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Platform '{payload.platform}' already linked for this user")

    handle = (payload.handle or "").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="handle must not be empty")

    # Normalize + validate the handle against the live platform before saving.
    # A bad handle stored here is the root cause of silent 0/0/0 syncs.
    if payload.platform == "codeforces":
        from app.adapters.codeforces import CodeforcesAPIError, CodeforcesAdapter

        cf_adapter = CodeforcesAdapter()
        try:
            info = await cf_adapter.get_user_info(handle)
            # Codeforces handles are case-insensitive; use the canonical casing
            # returned by the API so links and leaderboards stay consistent.
            handle = info.get("handle") or handle
        except CodeforcesAPIError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Handle not found on Codeforces: {handle}",
            )

    elif payload.platform == "leetcode":
        # Validate the account before persisting the link. Without this, a display
        # name (e.g. "Hues_Of_Code") or a stale session cookie can be stored as a
        # "linked" account and later produce a silent 0/0/0 sync.
        from app.adapters.leetcode import LeetCodeAPIError, LeetCodeAdapter

        lc_adapter = LeetCodeAdapter()
        try:
            if payload.auth_token:
                auth_user = await lc_adapter.get_authenticated_user(payload.auth_token)
                if not auth_user or not auth_user.get("username"):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "LeetCode cookie invalid or expired; paste a fresh "
                            "LEETCODE_SESSION cookie"
                        ),
                    )
                handle = auth_user["username"]
            else:
                profile = await lc_adapter.get_user_profile(handle)
                # Use LeetCode's canonical casing (handles are case-insensitive).
                handle = profile.get("username") or handle
        except LeetCodeAPIError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not validate LeetCode account '{handle}': {exc}",
            )

    # Optional LeetCode session cookie: accept the raw value, strip a leading
    # "LEETCODE_SESSION=" and surrounding quotes, encrypt at rest, never return it.
    raw_token = (payload.auth_token or "").strip()
    if raw_token:
        if raw_token.startswith('"') and raw_token.endswith('"') and len(raw_token) >= 2:
            raw_token = raw_token[1:-1]
        if raw_token.startswith("LEETCODE_SESSION="):
            raw_token = raw_token[len("LEETCODE_SESSION=") :]
        raw_token = raw_token.strip().strip('"').strip("'")

    submissions_available = payload.platform != "leetcode" or bool(raw_token)

    link = PlatformLink(
        user_id=payload.user_id,
        platform=payload.platform,
        handle=handle,
        auth_token=encrypt_token(raw_token) if raw_token else None,
        sync_status="queued",
        submissions_available=submissions_available,
    )
    db.add(link)
    # Commit before scheduling: the background task opens its own session and
    # must see the new row, and the response must return immediately.
    await db.commit()
    await db.refresh(link)
    background_tasks.add_task(run_link_sync, link.id)
    return link


@router.get("/platforms", response_model=List[PlatformLinkResponse])
async def list_platform_links(
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
    """List the platform links owned by the verified user."""
    stmt = (
        select(PlatformLink)
        .where(PlatformLink.user_id == user_id)
        .order_by(PlatformLink.id.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.delete("/platforms/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_platform(
    link_id: int,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    query = select(PlatformLink).where(PlatformLink.id == link_id)
    link = (await db.execute(query)).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Platform link not found")
    await assert_link_owner(db, external_id, link)
    await db.delete(link)
    return None


@router.get("/platforms/{link_id}/status", response_model=PlatformLinkResponse)
async def get_platform_status(
    link_id: int,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    query = select(PlatformLink).where(PlatformLink.id == link_id)
    link = (await db.execute(query)).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Platform link not found")
    await assert_link_owner(db, external_id, link)
    return link


@router.post("/platforms/{link_id}/sync", response_model=SyncTriggerResponse)
async def trigger_platform_sync(
    link_id: int,
    force_full: bool = Query(False),
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    link = (
        await db.execute(select(PlatformLink).where(PlatformLink.id == link_id))
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Platform link not found")
    await assert_link_owner(db, external_id, link)
    sync_service = CodeforcesSyncService()
    try:
        stats = await sync_service.sync_link(link_id, force_full=force_full)
        return SyncTriggerResponse(
            status="completed",
            link_id=link_id,
            user_id=stats["user_id"],
            submissions_fetched=stats["submissions_fetched"],
            submissions_newly_inserted=stats["submissions_newly_inserted"],
            contests_fetched=stats["contests_fetched"],
            contests_newly_inserted=stats["contests_newly_inserted"],
            problems_upserted=stats["problems_upserted"],
            submissions_synced=stats["submissions_synced"],
            contests_synced=stats["contests_synced"],
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
    _: User = Depends(require_user_scope),
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
    _: User = Depends(require_user_scope),
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
async def recompute_analytics(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
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
async def get_analytics_summary(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
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
    _: User = Depends(require_user_scope),
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
async def get_difficulty_distribution(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
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
async def get_contest_analytics(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
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
async def create_coach_session(
    payload: SessionCreateRequest,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    owner = (await db.execute(select(User).where(User.id == payload.user_id))).scalar_one_or_none()
    if not owner or owner.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this user",
        )
    coach_service = CoachService()
    try:
        session = await coach_service.create_session(
            user_id=payload.user_id,
            problem_id=payload.problem_id,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/coach/sessions", response_model=List[CoachSessionListItem])
async def list_coach_sessions(
    user_id: int = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
    stmt = (
        select(HintSession, Problem.title)
        .join(Problem, Problem.id == HintSession.problem_id)
        .where(HintSession.user_id == user_id)
        .order_by(HintSession.last_activity_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        CoachSessionListItem(
            id=s.id,
            problem_id=s.problem_id,
            problem_title=title,
            current_level=s.current_level,
            coach_mode=s.coach_mode,
            outcome=s.outcome,
            started_at=s.started_at,
            last_activity_at=s.last_activity_at,
        )
        for s, title in rows
    ]


@router.get("/coach/sessions/{session_id}", response_model=HintSessionDetailResponse)
async def get_coach_session(
    session_id: int,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(HintSession)
        .options(selectinload(HintSession.messages), selectinload(HintSession.problem))
        .where(HintSession.id == session_id)
    )
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail=f"HintSession id={session_id} not found")
    owner = (await db.execute(select(User).where(User.id == session.user_id))).scalar_one_or_none()
    if not owner or owner.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this coaching session",
        )
    return session


@router.post("/coach/sessions/{session_id}/message", response_model=SessionMessageResponse)
async def send_coach_message(
    session_id: int,
    payload: SessionMessageRequest,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    session_row = (
        await db.execute(select(HintSession).where(HintSession.id == session_id))
    ).scalar_one_or_none()
    if not session_row:
        raise HTTPException(status_code=404, detail=f"HintSession id={session_id} not found")
    owner = (await db.execute(select(User).where(User.id == session_row.user_id))).scalar_one_or_none()
    if not owner or owner.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this coaching session",
        )
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
async def conclude_coach_session(
    session_id: int,
    payload: SessionConcludeRequest,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    session_row = (
        await db.execute(select(HintSession).where(HintSession.id == session_id))
    ).scalar_one_or_none()
    if not session_row:
        raise HTTPException(status_code=404, detail=f"HintSession id={session_id} not found")
    owner = (await db.execute(select(User).where(User.id == session_row.user_id))).scalar_one_or_none()
    if not owner or owner.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this coaching session",
        )
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
async def generate_problem_recommendation(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
    """Generate and persist a problem or study recommendation for the user."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    result = await get_next_problem_recommendation(user_id)
    return result


@router.get("/recommendations/{user_id}", response_model=List[RecommendationListItem])
async def get_active_recommendations(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
    """List all active recommendations for the user."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return await list_active_recommendations(user_id)


@router.post("/recommendations/{recommendation_id}/dismiss", response_model=DismissResponse)
async def dismiss_rec(
    recommendation_id: int,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a recommendation by ID (owner only)."""
    rec = (
        await db.execute(select(Recommendation).where(Recommendation.id == recommendation_id))
    ).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    owner = (await db.execute(select(User).where(User.id == rec.user_id))).scalar_one_or_none()
    if not owner or owner.external_id != external_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this recommendation",
        )
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
    _: User = Depends(require_user_scope),
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


@router.get("/reflections", response_model=List[ReflectionListItem])
async def list_reflections(
    user_id: int = Query(...),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
):
    """List reflections for the owner, optionally filtered by date range."""
    stmt = select(Reflection).where(Reflection.user_id == user_id)
    try:
        if from_date:
            stmt = stmt.where(Reflection.date >= date_type.fromisoformat(from_date))
        if to_date:
            stmt = stmt.where(Reflection.date <= date_type.fromisoformat(to_date))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    stmt = stmt.order_by(Reflection.date.desc()).offset(offset).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        ReflectionListItem(
            id=r.id,
            date=r.date.isoformat(),
            content=r.content,
            metrics=r.metrics or {},
            generated_at=r.generated_at,
        )
        for r in rows
    ]


@router.get("/reflections/{user_id}/{date}", response_model=ReflectionResponse)
async def get_reflection_by_date(
    user_id: int,
    date: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_user_scope),
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

