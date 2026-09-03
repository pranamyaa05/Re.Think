"""FastAPI route definitions for users, platform links, sync, submissions, contests, and problems."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.contest_performance import ContestPerformance
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.schemas import (
    ContestPerformanceResponse,
    PlatformLinkCreate,
    PlatformLinkResponse,
    ProblemResponse,
    SubmissionResponse,
    SyncTriggerResponse,
    UserCreate,
    UserResponse,
)
from app.services.sync import CodeforcesSyncService, SyncAlreadyRunningError

router = APIRouter(prefix="/api")


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

    link = PlatformLink(
        user_id=payload.user_id,
        platform=payload.platform,
        handle=payload.handle,
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
async def trigger_platform_sync(link_id: int):
    sync_service = CodeforcesSyncService()
    try:
        stats = await sync_service.sync_link(link_id)
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
