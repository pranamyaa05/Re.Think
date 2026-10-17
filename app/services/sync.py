"""
Core synchronization service for Codeforces and LeetCode.

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
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codeforces import CodeforcesAdapter, CodeforcesAPIError
from app.adapters.leetcode import LeetCodeAdapter, LeetCodeAPIError
from app.config import settings
from app.database import async_session_factory
from app.models.contest_performance import ContestPerformance
from app.models.platform_link import PlatformLink
from app.models.problem import Problem
from app.models.submission import Submission
from app.utils.crypto import decrypt_token

logger = logging.getLogger(__name__)


class SyncAlreadyRunningError(Exception):
    """Raised when an active lease is currently held on this platform link."""
    pass


def _derive_leetcode_contest_id(title: str, start_time: int) -> int:
    """Derives a deterministic 32-bit positive integer contest ID for LeetCode contests."""
    match = re.search(r'(weekly|biweekly)\s+contest\s+(\d+)', title, re.IGNORECASE)
    if match:
        c_type, c_num = match.group(1).lower(), int(match.group(2))
        prefix = 100000 if c_type == 'weekly' else 200000
        return prefix + c_num
    if start_time and start_time > 0:
        return start_time % 2000000000
    return abs(hash(title)) % 2000000000


class CodeforcesSyncService:
    def __init__(
        self,
        adapter: Optional[CodeforcesAdapter] = None,
        leetcode_adapter: Optional[LeetCodeAdapter] = None,
    ):
        self.adapter = adapter or CodeforcesAdapter()
        self.leetcode_adapter = leetcode_adapter or LeetCodeAdapter()

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

    async def sync_link(
        self, link_id: int, force_full: bool = False, max_pages: Optional[int] = None
    ) -> Dict[str, Any]:
        worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        acquired = await self.acquire_lease(link_id, worker_id)
        if not acquired:
            raise SyncAlreadyRunningError(
                f"Sync lease could not be acquired for platform link {link_id}."
            )

        # Retrieve link details
        async with async_session_factory() as session:
            res = await session.execute(
                select(PlatformLink).where(PlatformLink.id == link_id)
            )
            link = res.scalar_one_or_none()
            if not link:
                raise ValueError(f"PlatformLink {link_id} not found")
            user_id = link.user_id
            handle = link.handle
            platform = link.platform
            auth_token = link.auth_token

        try:
            if platform == "leetcode":
                synced_subs, synced_contests, upserted_problems = await self._sync_leetcode(
                    user_id=user_id,
                    handle=handle,
                    auth_token=auth_token,
                )
            elif platform == "codeforces":
                synced_subs, synced_contests, upserted_problems = await self._sync_codeforces(
                    user_id=user_id,
                    handle=handle,
                    force_full=force_full,
                    max_pages=max_pages,
                )
            else:
                raise ValueError(f"Unsupported platform '{platform}' for link {link_id}")

            # Release lease on success
            released = await self.release_lease(link_id, worker_id, status="synced")
            if not released:
                logger.warning(f"Lease fence expired or stolen for worker {worker_id} on link {link_id}")

            # Post-sync analytics rebuild hook
            try:
                from app.services.analytics import AnalyticsService
                analytics_service = AnalyticsService()
                await analytics_service.recompute_user_analytics(user_id)
            except Exception as e:
                logger.exception(f"Post-sync analytics rebuild failed for user {user_id}: {e}")

            return {
                "submissions_synced": synced_subs,
                "contests_synced": synced_contests,
                "problems_upserted": upserted_problems,
            }

        except Exception as exc:
            logger.exception(f"Sync error on link {link_id}: {exc}")
            await self.release_lease(link_id, worker_id, status="failed", error=str(exc))
            raise

    # ── Codeforces Sync Flow ──────────────────────────────────────────────

    async def _sync_codeforces(
        self,
        user_id: int,
        handle: str,
        force_full: bool = False,
        max_pages: Optional[int] = None,
    ) -> Tuple[int, int, int]:
        # 1. Fetch user contest history from API (OUTSIDE DB transaction)
        raw_contests = await self.adapter.get_user_rating(handle)

        # 2. Synchronize submissions via stop-on-overlap pagination (OUTSIDE DB transaction per page)
        synced_subs, upserted_problems = await self._sync_submissions(
            user_id, handle, max_pages=max_pages, check_overlap=not force_full
        )

        # 3. Persist contest performances (idempotent upsert)
        synced_contests = await self._persist_contests(user_id, raw_contests)

        return synced_subs, synced_contests, upserted_problems

    async def _sync_submissions(
        self,
        user_id: int,
        handle: str,
        max_pages: Optional[int] = None,
        check_overlap: bool = True,
    ) -> Tuple[int, int]:
        page_size = settings.sync_page_size
        from_index = 1
        total_synced_subs = 0
        total_upserted_problems = 0
        page_count = 0
        seen_sync_sub_ids: Set[int] = set()

        while True:
            if max_pages is not None and page_count >= max_pages:
                logger.warning(
                    f"Reached explicit max_pages limit ({max_pages}) during submission sync for handle '{handle}'."
                )
                break

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

            # Infinite loop / cycle protection
            if all(sid in seen_sync_sub_ids for sid in sub_ids):
                logger.warning(
                    f"API cycle detected for handle '{handle}': all submission IDs on page {page_count} "
                    f"(from_index={from_index}) were already seen in this sync run. Terminating pagination."
                )
                break
            seen_sync_sub_ids.update(sub_ids)

            # Check for existing IDs in the database
            async with async_session_factory() as session:
                existing_res = await session.execute(
                    select(Submission.platform_sub_id).where(
                        Submission.user_id == user_id,
                        Submission.platform == "codeforces",
                        Submission.platform_sub_id.in_(sub_ids),
                    )
                )
                existing_ids: Set[int] = set(existing_res.scalars().all())

            new_submissions = [sub for sub in submissions_page if sub["id"] not in existing_ids]

            if new_submissions:
                prob_count = await self._upsert_problems_from_submissions(new_submissions)
                total_upserted_problems += prob_count

                inserted_count = await self._persist_submissions(user_id, new_submissions)
                total_synced_subs += inserted_count

            if (check_overlap and len(existing_ids) > 0) or len(submissions_page) < page_size:
                break

            from_index += len(submissions_page)

        return total_synced_subs, total_upserted_problems

    async def _upsert_problems_from_submissions(self, raw_submissions: List[Dict]) -> int:
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

    # ── LeetCode Sync Flow ────────────────────────────────────────────────

    async def _sync_leetcode(
        self,
        user_id: int,
        handle: str,
        auth_token: Optional[str] = None,
    ) -> Tuple[int, int, int]:
        raw_token = decrypt_token(auth_token) if auth_token else None

        # Auto-detect canonical username if session cookie is present
        if raw_token:
            auth_user = await self.leetcode_adapter.get_authenticated_user(raw_token)
            if auth_user and auth_user.get("username") and auth_user["username"] != handle:
                canonical = auth_user["username"]
                logger.info(
                    f"Auto-correcting LeetCode handle for user {user_id}: '{handle}' -> '{canonical}'"
                )
                handle = canonical
                async with async_session_factory() as session:
                    await session.execute(
                        text("UPDATE platform_links SET handle = :h WHERE user_id = :uid AND platform = 'leetcode'"),
                        {"h": canonical, "uid": user_id},
                    )
                    await session.commit()
        else:
            # Validate public user exists so typos/display names fail fast with clear message
            await self.leetcode_adapter.get_user_profile(handle)

        # 1. Contest performances (publicly accessible)
        contest_data = await self.leetcode_adapter.get_user_contest_ranking(
            handle, auth_token=raw_token
        )
        history = contest_data.get("history") or []
        synced_contests = await self._persist_leetcode_contests(user_id, history)

        # 2. Submissions & Problems (only with auth_token cookie)
        synced_subs = 0
        upserted_problems = 0
        if raw_token:
            synced_subs, upserted_problems = await self._sync_leetcode_submissions(
                user_id=user_id,
                handle=handle,
                raw_token=raw_token,
            )

        return synced_subs, synced_contests, upserted_problems

    async def _persist_leetcode_contests(
        self, user_id: int, raw_history: List[Dict]
    ) -> int:
        if not raw_history:
            return 0

        attended = [c for c in raw_history if c.get("attended")]
        if not attended:
            return 0

        # Sort chronologically by start time
        attended.sort(key=lambda c: c.get("contest", {}).get("startTime", 0))

        records = []
        prev_rating = 1500  # Standard initial rating on LeetCode
        for c in attended:
            contest_info = c.get("contest") or {}
            title = contest_info.get("title", "LeetCode Contest")
            start_time = contest_info.get("startTime", 0)
            contest_id = _derive_leetcode_contest_id(title, start_time)

            raw_rating = c.get("rating")
            curr_rating = round(float(raw_rating)) if raw_rating is not None else prev_rating
            update_time = datetime.fromtimestamp(start_time, tz=timezone.utc)

            records.append({
                "user_id": user_id,
                "platform": "leetcode",
                "contest_id": contest_id,
                "contest_name": title,
                "rating_before": prev_rating,
                "rating_after": curr_rating,
                "rank": int(c.get("ranking", 0)),
                "contest_date": update_time,
            })
            prev_rating = curr_rating

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

    async def _sync_leetcode_submissions(
        self, user_id: int, handle: str, raw_token: str
    ) -> Tuple[int, int]:
        recent_subs = await self.leetcode_adapter.get_recent_submissions(
            handle, limit=100, auth_token=raw_token
        )
        if not recent_subs:
            return 0, 0

        sub_ids = []
        for s in recent_subs:
            try:
                sub_ids.append(int(s["id"]))
            except (ValueError, TypeError):
                continue

        if not sub_ids:
            return 0, 0

        # Check existing submissions in DB
        async with async_session_factory() as session:
            existing_res = await session.execute(
                select(Submission.platform_sub_id).where(
                    Submission.user_id == user_id,
                    Submission.platform == "leetcode",
                    Submission.platform_sub_id.in_(sub_ids),
                )
            )
            existing_ids: Set[int] = set(existing_res.scalars().all())

        new_subs = [s for s in recent_subs if int(s["id"]) not in existing_ids]
        if not new_subs:
            return 0, 0

        # Step A: Upsert problems for new submissions
        total_upserted_problems = await self._upsert_leetcode_problems(new_subs)

        # Step B: Insert submissions
        total_synced_subs = await self._persist_leetcode_submissions(user_id, new_subs)

        return total_synced_subs, total_upserted_problems

    async def _upsert_leetcode_problems(self, raw_submissions: List[Dict]) -> int:
        slugs = list({s["titleSlug"] for s in raw_submissions if s.get("titleSlug")})
        if not slugs:
            return 0

        async with async_session_factory() as session:
            existing_res = await session.execute(
                select(Problem.platform_id).where(
                    Problem.platform == "leetcode",
                    Problem.platform_id.in_(slugs),
                )
            )
            existing_slugs = set(existing_res.scalars().all())

        needed_slugs = [slug for slug in slugs if slug not in existing_slugs]
        problems_to_insert = []

        for slug in needed_slugs:
            q_data = None
            try:
                q_data = await self.leetcode_adapter.get_problem_by_slug(slug)
            except Exception as e:
                logger.warning(f"Could not fetch problem details for slug '{slug}': {e}")

            sub_item = next((s for s in raw_submissions if s.get("titleSlug") == slug), {})
            title = (q_data.get("title") if q_data else None) or sub_item.get("title") or slug.replace("-", " ").title()
            difficulty = q_data.get("difficulty") if q_data else None
            tags = [t.get("name") for t in q_data.get("topicTags", [])] if q_data and q_data.get("topicTags") else []

            problems_to_insert.append({
                "platform": "leetcode",
                "platform_id": slug,
                "title": title,
                "rating": None,  # Decision 1: rating is None for LC
                "difficulty_label": difficulty,  # Easy / Medium / Hard
                "tags": tags,
                "url": f"https://leetcode.com/problems/{slug}/",
                "solved_count": 0,
            })

        if not problems_to_insert:
            return 0

        async with async_session_factory() as session:
            stmt = insert(Problem).values(problems_to_insert)
            stmt = stmt.on_conflict_do_update(
                index_elements=["platform", "platform_id"],
                set_={
                    "title": stmt.excluded.title,
                    "difficulty_label": stmt.excluded.difficulty_label,
                    "tags": stmt.excluded.tags,
                    "url": stmt.excluded.url,
                }
            )
            await session.execute(stmt)
            await session.commit()

        return len(problems_to_insert)

    async def _persist_leetcode_submissions(
        self, user_id: int, raw_submissions: List[Dict]
    ) -> int:
        slugs = [s.get("titleSlug") for s in raw_submissions if s.get("titleSlug")]
        if not slugs:
            return 0

        async with async_session_factory() as session:
            result = await session.execute(
                select(Problem.platform_id, Problem.id).where(
                    Problem.platform == "leetcode",
                    Problem.platform_id.in_(slugs),
                )
            )
            prob_id_map = dict(result.all())

        sub_records = []
        for sub in raw_submissions:
            slug = sub.get("titleSlug")
            db_prob_id = prob_id_map.get(slug)
            if not db_prob_id:
                continue

            created_time = datetime.fromtimestamp(
                sub.get("timestamp", 0), tz=timezone.utc
            )

            sub_records.append({
                "user_id": user_id,
                "problem_id": db_prob_id,
                "platform": "leetcode",
                "platform_sub_id": int(sub["id"]),
                "verdict": sub.get("verdict", "UNKNOWN"),
                "language": sub.get("lang"),
                "submitted_at": created_time,
                "time_ms": None,
                "memory_bytes": None,
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


# Alias PlatformSyncService to CodeforcesSyncService for unified naming
PlatformSyncService = CodeforcesSyncService
