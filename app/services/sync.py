"""
Core synchronization service for Codeforces.

Guarantees:
1. Atomic Lease: Non-blocking lease acquisition with timeout recovery.
2. Connection safety: External HTTP requests happen OUTSIDE any DB connection/transaction.
3. Fenced release: Release queries assert sync_worker_id to avoid overwriting state on race.
4. Problem-First Upsert: Upserts problems first to satisfy foreign key constraints.
5. Idempotent Submissions & Contests: ON CONFLICT DO NOTHING guarantees no duplicate entries.
6. Stop-on-Overlap Pagination: Paginates newest-first and terminates early when hitting existing submissions.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, List, Optional, Set, Tuple
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codeforces import CodeforcesAdapter, CodeforcesAPIError
from app.config import settings
from app.database import async_session_factory
from app.models.contest_performance import ContestPerformance
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.submission import Submission

logger = logging.getLogger(__name__)


class SyncAlreadyRunningError(Exception):
    """Raised when an active lease is currently held on this platform link."""
    pass


class CodeforcesSyncService:
    def __init__(self, adapter: Optional[CodeforcesAdapter] = None):
        self.adapter = adapter or CodeforcesAdapter()

    async def acquire_lease(self, link_id: int, worker_id: str) -> bool:
        """
        Attempts to acquire an exclusive atomic lease on the platform link.
        Succeeds if link is idle OR if the previous lease has expired.
        Connection is released back to pool immediately after.
        """
        lease_minutes = settings.sync_lease_minutes
        query = text(f"""
            UPDATE platform_links
            SET sync_status = 'syncing',
                sync_worker_id = :worker_id,
                lease_expires_at = NOW() + INTERVAL '{lease_minutes} minutes',
                sync_error = NULL
            WHERE id = :link_id
              AND (
                  sync_status != 'syncing'
                  OR lease_expires_at < NOW()
              )
            RETURNING id;
        """)

        async with async_session_factory() as session:
            result = await session.execute(
                query,
                {"link_id": link_id, "worker_id": worker_id}
            )
            await session.commit()
            return result.fetchone() is not None

    async def release_lease(
        self,
        link_id: int,
        worker_id: str,
        status: str,
        error: Optional[str] = None
    ) -> bool:
        """
        Releases the sync lease, strictly fenced by sync_worker_id.
        If the lease was stolen/expired, 0 rows are updated.
        """
        query = text("""
            UPDATE platform_links
            SET sync_status = CAST(:status AS VARCHAR(20)),
                sync_worker_id = NULL,
                lease_expires_at = NULL,
                sync_error = :error,
                last_synced_at = CASE WHEN CAST(:status AS VARCHAR(20)) = 'synced' THEN NOW() ELSE last_synced_at END
            WHERE id = :link_id
              AND sync_worker_id = :worker_id
            RETURNING id;
        """)

        async with async_session_factory() as session:
            result = await session.execute(
                query,
                {
                    "link_id": link_id,
                    "worker_id": worker_id,
                    "status": status,
                    "error": error,
                }
            )
            await session.commit()
            return result.fetchone() is not None

    async def sync_link(self, link_id: int) -> Dict[str, int]:
        """
        Orchestrates full Codeforces sync with atomic lease and safety boundaries.
        Returns statistics: {'submissions_synced': N, 'contests_synced': M, 'problems_upserted': K}
        """
        worker_id = f"worker-{uuid.uuid4().hex[:12]}"
        acquired = await self.acquire_lease(link_id, worker_id)
        if not acquired:
            raise SyncAlreadyRunningError(f"Sync is already in progress for link {link_id}")

        # Fetch handle and user_id safely
        async with async_session_factory() as session:
            result = await session.execute(
                select(PlatformLink).where(PlatformLink.id == link_id)
            )
            link = result.scalar_one_or_none()
            if not link:
                await self.release_lease(link_id, worker_id, status="failed", error="Link not found")
                raise ValueError(f"PlatformLink {link_id} not found")
            user_id = link.user_id
            handle = link.handle

        try:
            # 1. Fetch user contest history from API (OUTSIDE DB transaction)
            raw_contests = await self.adapter.get_user_rating(handle)

            # 2. Synchronize submissions via stop-on-overlap pagination (OUTSIDE DB transaction per page)
            synced_subs, upserted_problems = await self._sync_submissions(user_id, handle)

            # 3. Persist contest performances (idempotent upsert)
            synced_contests = await self._persist_contests(user_id, raw_contests)

            # 4. Release lease on success
            released = await self.release_lease(link_id, worker_id, status="synced")
            if not released:
                logger.warning(f"Lease fence expired or stolen for worker {worker_id} on link {link_id}")

            return {
                "submissions_synced": synced_subs,
                "contests_synced": synced_contests,
                "problems_upserted": upserted_problems,
            }

        except Exception as exc:
            logger.exception(f"Sync error on link {link_id}: {exc}")
            await self.release_lease(link_id, worker_id, status="failed", error=str(exc))
            raise

    async def _sync_submissions(
        self, user_id: int, handle: str, max_pages: int = 10
    ) -> Tuple[int, int]:
        """
        Paginates submissions newest-first.
        Stops when encountering submissions already known in DB (overlap) or reaches max_pages.
        """
        page_size = settings.sync_page_size
        from_index = 1
        total_synced_subs = 0
        total_upserted_problems = 0
        page_count = 0

        while page_count < max_pages:
            page_count += 1
            # API call outside DB session
            submissions_page = await self.adapter.get_user_status(
                handle=handle, from_index=from_index, count=page_size
            )
            if not submissions_page:
                break

            sub_ids = [sub["id"] for sub in submissions_page if "id" in sub]
            if not sub_ids:
                break

            # Check for existing IDs to determine overlap
            async with async_session_factory() as session:
                existing_res = await session.execute(
                    select(Submission.platform_sub_id).where(
                        Submission.user_id == user_id,
                        Submission.platform == "codeforces",
                        Submission.platform_sub_id.in_(sub_ids),
                    )
                )
                existing_ids: Set[int] = set(existing_res.scalars().all())

            # Filter out already existing submissions
            new_submissions = [sub for sub in submissions_page if sub["id"] not in existing_ids]

            if new_submissions:
                # Step A: Upsert problems for these submissions first (FK dependency)
                prob_count = await self._upsert_problems_from_submissions(new_submissions)
                total_upserted_problems += prob_count

                # Step B: Insert the new submissions idempotently
                inserted_count = await self._persist_submissions(user_id, new_submissions)
                total_synced_subs += inserted_count

            # If any item in the page was already known, we have reached the overlap!
            if len(existing_ids) > 0 or len(submissions_page) < page_size:
                break

            from_index += page_size

        return total_synced_subs, total_upserted_problems

    async def _upsert_problems_from_submissions(self, raw_submissions: List[Dict]) -> int:
        """Extracts embedded problems and upserts them into problems table."""
        problems_map: Dict[str, Dict] = {}
        for sub in raw_submissions:
            prob = sub.get("problem")
            if not prob:
                continue
            contest_id = prob.get("contestId")
            index = prob.get("index")
            if not contest_id or not index:
                continue

            platform_id = f"{contest_id}_{index}"
            if platform_id not in problems_map:
                problems_map[platform_id] = {
                    "platform": "codeforces",
                    "platform_id": platform_id,
                    "contest_id": contest_id,
                    "problem_index": str(index),
                    "title": prob.get("name", f"Problem {index}"),
                    "rating": prob.get("rating"),
                    "tags": prob.get("tags") or [],
                    "url": f"https://codeforces.com/contest/{contest_id}/problem/{index}",
                }

        if not problems_map:
            return 0

        values = list(problems_map.values())
        async with async_session_factory() as session:
            stmt = insert(Problem).values(values)
            # On conflict update title, rating, tags, and url in case problem details updated
            stmt = stmt.on_conflict_do_update(
                index_elements=["platform", "platform_id"],
                set_={
                    "title": stmt.excluded.title,
                    "rating": stmt.excluded.rating,
                    "tags": stmt.excluded.tags,
                    "url": stmt.excluded.url,
                }
            )
            await session.execute(stmt)
            await session.commit()

        return len(values)

    async def _persist_submissions(self, user_id: int, raw_submissions: List[Dict]) -> int:
        """Inserts submissions with resolved problem_id foreign keys, using ON CONFLICT DO NOTHING."""
        # Query problem primary key IDs for the platform_ids
        platform_ids = [
            f"{sub['problem']['contestId']}_{sub['problem']['index']}"
            for sub in raw_submissions
            if sub.get("problem") and sub["problem"].get("contestId") and sub["problem"].get("index")
        ]
        if not platform_ids:
            return 0

        async with async_session_factory() as session:
            result = await session.execute(
                select(Problem.platform_id, Problem.id).where(
                    Problem.platform == "codeforces",
                    Problem.platform_id.in_(platform_ids),
                )
            )
            prob_id_map = dict(result.all())

        sub_records = []
        for sub in raw_submissions:
            prob = sub.get("problem", {})
            p_id = f"{prob.get('contestId')}_{prob.get('index')}"
            db_prob_id = prob_id_map.get(p_id)
            if not db_prob_id:
                continue

            created_time = datetime.fromtimestamp(
                sub.get("creationTimeSeconds", 0), tz=timezone.utc
            )
            author = sub.get("author", {})

            sub_records.append({
                "user_id": user_id,
                "problem_id": db_prob_id,
                "platform": "codeforces",
                "platform_sub_id": sub["id"],
                "verdict": sub.get("verdict", "UNKNOWN"),
                "language": sub.get("programmingLanguage"),
                "submitted_at": created_time,
                "time_ms": sub.get("timeConsumedMillis"),
                "memory_bytes": sub.get("memoryConsumedBytes"),
                "contest_id": sub.get("contestId"),
                "participant_type": author.get("participantType"),
                "relative_time_s": sub.get("relativeTimeSeconds"),
                "passed_test_count": sub.get("passedTestCount"),
            })

        if not sub_records:
            return 0

        async with async_session_factory() as session:
            stmt = insert(Submission).values(sub_records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["user_id", "platform", "platform_sub_id"]
            )
            res = await session.execute(stmt)
            await session.commit()
            return res.rowcount if res.rowcount is not None else len(sub_records)

    async def _persist_contests(self, user_id: int, raw_contests: List[Dict]) -> int:
        """Idempotently saves user rating changes from Codeforces."""
        if not raw_contests:
            return 0

        records = []
        for c in raw_contests:
            contest_id = c.get("contestId")
            if not contest_id:
                continue
            update_time = datetime.fromtimestamp(
                c.get("ratingUpdateTimeSeconds", 0), tz=timezone.utc
            )
            records.append({
                "user_id": user_id,
                "platform": "codeforces",
                "contest_id": contest_id,
                "contest_name": c.get("contestName", f"Contest {contest_id}"),
                "rating_before": c.get("oldRating", 0),
                "rating_after": c.get("newRating", 0),
                "rank": c.get("rank", 0),
                "contest_date": update_time,
            })

        if not records:
            return 0

        async with async_session_factory() as session:
            stmt = insert(ContestPerformance).values(records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["user_id", "platform", "contest_id"]
            )
            res = await session.execute(stmt)
            await session.commit()
            return res.rowcount if res.rowcount is not None else len(records)
