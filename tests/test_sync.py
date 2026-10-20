"""
Tests for submission sync pagination, stop-on-overlap, and boundary conditions.

Covers:
1. Full-history first sync exceeding 10 pages without truncation.
2. Incremental sync stopping on overlap (boundary page with mix of new and existing).
3. Final short page termination.
4. Idempotency (no duplicate submissions after repeated sync).
5. Infinite-loop / cycle protection.
"""

import uuid
import pytest
from sqlalchemy import select, func
from app.database import async_session_factory, engine
from app.models.submission import Submission
from app.models.user import User
from app.services.sync import CodeforcesSyncService


def make_submission(sub_id: int, contest_id: int = 100, index: str = "A"):
    """Generates a realistic Codeforces API submission payload."""
    return {
        "id": sub_id,
        "contestId": contest_id,
        "creationTimeSeconds": 1700000000 + sub_id,
        "relativeTimeSeconds": 1000,
        "problem": {
            "contestId": contest_id,
            "index": index,
            "name": f"Problem {contest_id}{index}",
            "type": "PROGRAMMING",
            "rating": 1500,
            "tags": ["greedy", "math"],
        },
        "author": {
            "contestId": contest_id,
            "members": [{"handle": "tester"}],
            "participantType": "PRACTICE",
            "ghost": False,
        },
        "programmingLanguage": "GNU C++20",
        "verdict": "OK",
        "testset": "TESTS",
        "passedTestCount": 15,
        "timeConsumedMillis": 150,
        "memoryConsumedBytes": 1048576,
    }


class MockCodeforcesAdapter:
    def __init__(self, submissions_newest_first: list):
        self.submissions = submissions_newest_first
        self.calls = []

    async def get_user_status(self, handle: str, from_index: int, count: int):
        self.calls.append((from_index, count))
        # from_index is 1-based offset in Codeforces API
        start = from_index - 1
        end = start + count
        return self.submissions[start:end]

    async def get_user_rating(self, handle: str):
        return []


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


async def create_test_user() -> int:
    async with async_session_factory() as session:
        user = User(username=f"sync_test_{uuid.uuid4().hex[:8]}")
        session.add(user)
        await session.commit()
        return user.id


@pytest.mark.asyncio
async def test_first_sync_exceeding_10_pages():
    """
    Verifies that a user's first sync fetches the entire history even when it
    exceeds 10 pages (1250 submissions = 12 full pages of 100 + 1 short page of 50).
    Ensures the old 10-page bug does not truncate the history.
    """
    user_id = await create_test_user()

    # 1250 submissions: IDs 1250 down to 1
    mock_data = [make_submission(i) for i in range(1250, 0, -1)]
    adapter = MockCodeforcesAdapter(mock_data)
    service = CodeforcesSyncService(adapter=adapter)

    fetched_count, synced_count, problems_count = await service._sync_submissions(user_id, "tester")

    assert synced_count == 1250
    # 12 full pages (100 each) + 1 short page (50 items) = 13 pages fetched
    assert len(adapter.calls) == 13
    assert adapter.calls[0] == (1, 100)
    assert adapter.calls[9] == (901, 100)   # Page 10
    assert adapter.calls[10] == (1001, 100) # Page 11 (exceeds 10!)
    assert adapter.calls[11] == (1101, 100) # Page 12
    assert adapter.calls[12] == (1201, 100) # Page 13 (final 50)

    # Verify count in DB
    async with async_session_factory() as session:
        count_res = await session.execute(
            select(func.count(Submission.id)).where(Submission.user_id == user_id)
        )
        assert count_res.scalar_one() == 1250


@pytest.mark.asyncio
async def test_incremental_sync_stopping_on_overlap():
    """
    Verifies that on subsequent syncs:
    1. A page containing a mix of new and existing submissions safely persists the new ones.
    2. Pagination stops immediately on that boundary page without fetching older pages.
    """
    user_id = await create_test_user()

    # Step 1: Initial sync of 200 submissions (IDs 200 down to 1)
    initial_data = [make_submission(i) for i in range(200, 0, -1)]
    adapter1 = MockCodeforcesAdapter(initial_data)
    service1 = CodeforcesSyncService(adapter=adapter1)
    _, synced1, _ = await service1._sync_submissions(user_id, "tester")
    assert synced1 == 200
    assert len(adapter1.calls) == 3  # 2 full pages of 100 + 1 empty page (since 200 is exact multiple of 100)

    # Step 2: User makes 5 new submissions: IDs 205, 204, 203, 202, 201
    updated_data = [make_submission(i) for i in range(205, 0, -1)]
    adapter2 = MockCodeforcesAdapter(updated_data)
    service2 = CodeforcesSyncService(adapter=adapter2)

    _, synced2, _ = await service2._sync_submissions(user_id, "tester")

    # Only the 5 new submissions should be synced
    assert synced2 == 5

    # Exactly 1 page was fetched because it stopped on overlap!
    # Page 1 contained 5 new submissions and 95 existing submissions.
    assert len(adapter2.calls) == 1
    assert adapter2.calls[0] == (1, 100)

    # DB should now have 205 total submissions
    async with async_session_factory() as session:
        count_res = await session.execute(
            select(func.count(Submission.id)).where(Submission.user_id == user_id)
        )
        assert count_res.scalar_one() == 205


@pytest.mark.asyncio
async def test_final_short_page_termination():
    """
    Verifies that when the final page is shorter than page_size (< 100),
    pagination cleanly terminates without making further API calls.
    """
    user_id = await create_test_user()

    # User with only 42 total submissions
    short_data = [make_submission(i) for i in range(42, 0, -1)]
    adapter = MockCodeforcesAdapter(short_data)
    service = CodeforcesSyncService(adapter=adapter)

    _, synced, _ = await service._sync_submissions(user_id, "tester")

    assert synced == 42
    # Only 1 call made; stopped because len(page) == 42 < 100
    assert len(adapter.calls) == 1
    assert adapter.calls[0] == (1, 100)

    async with async_session_factory() as session:
        count_res = await session.execute(
            select(func.count(Submission.id)).where(Submission.user_id == user_id)
        )
        assert count_res.scalar_one() == 42


@pytest.mark.asyncio
async def test_no_duplicate_submissions_after_repeated_sync():
    """
    Verifies that calling sync repeatedly with the exact same data produces
    0 new submissions inserted and 0 duplicates in the database.
    """
    user_id = await create_test_user()

    data = [make_submission(i) for i in range(50, 0, -1)]
    adapter = MockCodeforcesAdapter(data)
    service = CodeforcesSyncService(adapter=adapter)

    # First sync
    _, synced1, _ = await service._sync_submissions(user_id, "tester")
    assert synced1 == 50

    # Second sync (identical data)
    _, synced2, _ = await service._sync_submissions(user_id, "tester")
    assert synced2 == 0

    # Exactly 1 call was made on the second sync (stopped on overlap)
    assert len(adapter.calls) == 2

    # Total in DB is still 50
    async with async_session_factory() as session:
        count_res = await session.execute(
            select(func.count(Submission.id)).where(Submission.user_id == user_id)
        )
        assert count_res.scalar_one() == 50


@pytest.mark.asyncio
async def test_infinite_loop_cycle_protection():
    """
    Verifies that if an API returns the same page of submissions repeatedly,
    the cycle protection detects it and terminates the loop safely.
    """
    user_id = await create_test_user()

    class BuggyCyclingAdapter:
        def __init__(self):
            self.calls = []

        async def get_user_status(self, handle: str, from_index: int, count: int):
            self.calls.append((from_index, count))
            # Always returns the exact same 100 submissions regardless of from_index
            return [make_submission(i) for i in range(100, 0, -1)]

        async def get_user_rating(self, handle: str):
            return []

    adapter = BuggyCyclingAdapter()
    service = CodeforcesSyncService(adapter=adapter)

    _, synced, _ = await service._sync_submissions(user_id, "tester")

    assert synced == 100
    # Breaks on page 2 because all IDs were already seen in this sync run
    assert len(adapter.calls) == 2
