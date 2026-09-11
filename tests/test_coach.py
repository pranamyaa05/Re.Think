"""
Unit tests for Socratic Coaching Engine, FSM transition router,
and Two-Tier Guardrails.
"""

import uuid
import pytest

from app.database import async_session_factory, engine
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.models.user import User
from app.services.coach import (
    CoachService,
    evaluate_tier1_guardrails,
    evaluate_tier2_judge,
    evaluate_fsm_transition,
)
from app.services.llm import LLMClient


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


def test_evaluate_tier1_guardrails_code_fences():
    # Code fence at L0-L3 should be blocked
    text_with_fence = "Here is a hint:\n```\nint x = 5;\n```"
    passed_l0, reason_l0 = evaluate_tier1_guardrails(text_with_fence, level=0)
    assert not passed_l0
    assert "Code blocks" in reason_l0

    passed_l2, reason_l2 = evaluate_tier1_guardrails(text_with_fence, level=2)
    assert not passed_l2

    # Clean conceptual text without fence should pass
    clean_text = "Consider what happens to the sum when you add elements sequentially."
    passed_clean, _ = evaluate_tier1_guardrails(clean_text, level=0)
    assert passed_clean


def test_evaluate_tier1_guardrails_imperative_recipes():
    recipe_1 = "Step 1: Sort the array. Step 2: Loop through each element."
    passed_r1, reason_r1 = evaluate_tier1_guardrails(recipe_1, level=2)
    assert not passed_r1
    assert "Imperative recipe" in reason_r1

    recipe_2 = "First allocate a vector of size N to store intermediate values."
    passed_r2, reason_r2 = evaluate_tier1_guardrails(recipe_2, level=3)
    assert not passed_r2


def test_evaluate_tier1_guardrails_premature_technique():
    # Dijkstra or DP mentioned at L0/L1 must be blocked
    text_dijkstra = "You can use Dijkstra's algorithm to find the shortest paths."
    passed_l0, reason_l0 = evaluate_tier1_guardrails(text_dijkstra, level=0)
    assert not passed_l0
    assert "Premature technique reveal" in reason_l0

    passed_l1, reason_l1 = evaluate_tier1_guardrails(text_dijkstra, level=1)
    assert not passed_l1

    # At L2, naming the technique is allowed (Algorithmic Direction level)
    passed_l2, reason_l2 = evaluate_tier1_guardrails(text_dijkstra, level=2)
    assert passed_l2

    # Custom problem-specific technique from knowledge
    text_custom = "This is a heavy centroid problem."
    passed_custom, _ = evaluate_tier1_guardrails(
        text_custom, level=0, knowledge_techniques=["heavy centroid"]
    )
    assert not passed_custom


def test_evaluate_tier1_guardrails_l4_syntax():
    # Python code syntax at L4 must be blocked
    py_code = "def solve(n):\n    return n * 2"
    passed_py, reason_py = evaluate_tier1_guardrails(py_code, level=4)
    assert not passed_py
    assert "prohibited language syntax detected" in reason_py

    # C++ code syntax at L4 must be blocked
    cpp_code = "#include <iostream>\nvector<int> a;"
    passed_cpp, reason_cpp = evaluate_tier1_guardrails(cpp_code, level=4)
    assert not passed_cpp
    assert "prohibited language syntax detected" in reason_cpp

    # Mathematical pseudocode at L4 should pass
    math_pseudo = """
    1. Define S(i) as the maximum subarray sum ending at index i.
    2. Base case: S(0) = 0.
    3. Transition: For each i from 1 to n, compute S(i) = max(A[i], S(i - 1) + A[i]).
    4. Return the maximum value among all S(i).
    """
    passed_math, _ = evaluate_tier1_guardrails(math_pseudo, level=4)
    assert passed_math


@pytest.mark.asyncio
async def test_evaluate_tier2_judge():
    client = LLMClient(provider="mock")
    checklist = await evaluate_tier2_judge(
        llm_client=client,
        hint_content="Consider the parity of the prefix sums.",
        problem_title="Subarray Parity",
        level=1,
    )
    assert isinstance(checklist, dict)
    assert "reveals_full_solution" in checklist
    assert "contains_executable_code" in checklist
    assert "exceeds_level_guidance" in checklist
    assert "lacks_problem_context" in checklist
    assert "is_vacuous" in checklist
    assert checklist["reveals_full_solution"] is False


@pytest.mark.asyncio
async def test_fsm_evaluator_escalation():
    client = LLMClient(provider="mock")
    eval_result = await evaluate_fsm_transition(
        llm_client=client,
        problem_title="Interval Graph",
        current_level=0,
        user_message="I'm stuck, just tell me what algorithm to use.",
        request_escalation=True,
    )
    assert eval_result["understood_current_level"] is True
    assert eval_result["recommended_next_level"] >= 2


@pytest.mark.asyncio
async def test_coach_service_session_lifecycle():
    # 1. Seed user and problem
    async with async_session_factory() as session:
        user = User(username=f"user_{uuid.uuid4().hex[:6]}")
        session.add(user)
        prob = Problem(
            platform="codeforces",
            platform_id=f"9998_{uuid.uuid4().hex[:6]}",
            title="Max Segment Overlap",
            rating=1500,
            problem_index="B",
            tags=["greedy", "sortings"],
        )
        session.add(prob)
        await session.commit()
        user_id = user.id
        prob_id = prob.id

        # Seed knowledge
        knowledge = ProblemKnowledge(
            problem_id=prob_id,
            source_type="official_editorial",
            extraction_method="heading_match",
            validation_status="user_verified",
            approach_summary="Sort intervals by finish time and greedily take non-overlapping.",
            key_insight="Earliest finishing leaves the most room for future intervals.",
            techniques=["greedy", "sortings"],
            common_pitfalls=["Sorting by start time"],
        )
        session.add(knowledge)
        await session.commit()

    coach_service = CoachService(llm_client=LLMClient(provider="mock"))

    # 2. Create coaching session
    created_session = await coach_service.create_session(user_id=user_id, problem_id=prob_id)
    assert created_session.user_id == user_id
    assert created_session.problem_id == prob_id
    assert created_session.coach_mode == "full_coach"  # verified official editorial
    assert created_session.current_level == 0
    assert created_session.outcome == "ongoing"
    assert len(created_session.messages) == 1
    assert created_session.messages[0].role == "coach"
    assert created_session.messages[0].hint_level == 0
    assert created_session.messages[0].leakage_checklist is not None

    session_id = created_session.id

    # 3. Process user message with current code snapshot
    code_draft = "def solve():\n    # sorting intervals by start time\n    pass"
    coach_reply, updated_session = await coach_service.process_user_message(
        session_id=session_id,
        user_message="I tried sorting by start time, but it seems to fail on nested intervals.",
        current_code=code_draft,
    )

    assert coach_reply.role == "coach"
    assert updated_session.current_level >= 1
    # Check that user's code snapshot was preserved on their message
    async with async_session_factory() as session:
        from sqlalchemy import select
        from app.models.hint_message import HintMessage
        res = await session.execute(
            select(HintMessage).where(
                HintMessage.session_id == session_id,
                HintMessage.role == "user",
            )
        )
        user_msg = res.scalar_one()
        assert user_msg.code_snapshot == code_draft

    # 4. Conclude session
    concluded = await coach_service.conclude_session(session_id=session_id, outcome="solved")
    assert concluded.outcome == "solved"
    assert concluded.solved_at is not None
