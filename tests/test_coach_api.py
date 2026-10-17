"""Integration tests for Phase 3 Editorial Knowledge and Coach API endpoints."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import async_session_factory, engine
from app.main import app
from app.models.problem import Problem
from app.models.user import User


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_and_coach_api_flow():
    # 1. Seed problem and user
    prob_platform_id = f"8888_{uuid.uuid4().hex[:6]}"
    async with async_session_factory() as session:
        user = User(username=f"coach_user_{uuid.uuid4().hex[:6]}")
        session.add(user)

        prob = Problem(
            platform="codeforces",
            platform_id=prob_platform_id,
            title="Two Arrays and Sums",
            rating=1600,
            problem_index="C",
            tags=["binary search", "two pointers"],
        )
        session.add(prob)
        await session.commit()
        user_id = user.id
        prob_id = prob.id

    headers = {"X-API-Key": settings.api_key}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as ac:
        # 2. Extract knowledge via POST /api/knowledge/extract
        editorial_text = """
        <h3>Problem C. Two Arrays and Sums</h3>
        <p>Sort both arrays. For each element in the first array, binary search for the complementary
        element in the second array. The total time complexity is $O(N \\log N)$.</p>
        """
        ext_res = await ac.post(
            "/api/knowledge/extract",
            json={
                "problem_id": prob_id,
                "editorial_text": editorial_text,
                "editorial_url": "https://codeforces.com/blog/entry/77777",
            },
        )
        assert ext_res.status_code == 201
        know_data = ext_res.json()
        assert know_data["problem_id"] == prob_id
        assert know_data["source_type"] == "official_editorial"
        assert know_data["extraction_method"] == "heading_match"
        assert know_data["coach_mode"] == "cautious_coach"  # unchecked official editorial
        knowledge_id = know_data["id"]

        # 3. Fetch knowledge via GET /api/knowledge/{problem_id}
        get_know = await ac.get(f"/api/knowledge/{prob_id}")
        assert get_know.status_code == 200
        assert get_know.json()["id"] == knowledge_id

        # 4. Verify knowledge via POST /api/knowledge/{id}/verify
        ver_res = await ac.post(
            f"/api/knowledge/{knowledge_id}/verify",
            json={"status": "user_verified"},
        )
        assert ver_res.status_code == 200
        assert ver_res.json()["validation_status"] == "user_verified"
        assert ver_res.json()["coach_mode"] == "full_coach"

        # 5. Create coaching session via POST /api/coach/sessions
        sess_create_res = await ac.post(
            "/api/coach/sessions",
            json={"user_id": user_id, "problem_id": prob_id},
        )
        assert sess_create_res.status_code == 201
        sess_data = sess_create_res.json()
        session_id = sess_data["id"]
        assert sess_data["user_id"] == user_id
        assert sess_data["problem_id"] == prob_id
        assert sess_data["coach_mode"] == "full_coach"
        assert sess_data["current_level"] == 0
        assert len(sess_data["messages"]) == 1
        assert sess_data["messages"][0]["role"] == "coach"
        assert sess_data["messages"][0]["hint_level"] == 0

        # 6. Fetch session details via GET /api/coach/sessions/{session_id}
        sess_get_res = await ac.get(f"/api/coach/sessions/{session_id}")
        assert sess_get_res.status_code == 200
        assert sess_get_res.json()["id"] == session_id

        # 7. Post user message with code snapshot via POST /api/coach/sessions/{session_id}/message
        code_draft = "def solve():\n    # check all pairs in O(N^2)\n    pass"
        msg_res = await ac.post(
            f"/api/coach/sessions/{session_id}/message",
            json={
                "user_message": "An $O(N^2)$ brute force is too slow because $N \\le 10^5$. Can we sort first?",
                "current_code": code_draft,
                "request_escalation": False,
            },
        )
        assert msg_res.status_code == 200
        msg_data = msg_res.json()
        assert "coach_message" in msg_data
        assert msg_data["coach_message"]["role"] == "coach"
        assert msg_data["current_level"] >= 1

        # 8. Conclude session via POST /api/coach/sessions/{session_id}/conclude
        conc_res = await ac.post(
            f"/api/coach/sessions/{session_id}/conclude",
            json={"outcome": "solved"},
        )
        assert conc_res.status_code == 200
        conc_data = conc_res.json()
        assert conc_data["outcome"] == "solved"
        assert conc_data["solved_at"] is not None
