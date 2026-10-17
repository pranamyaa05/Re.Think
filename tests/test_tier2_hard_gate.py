import pytest
from unittest.mock import AsyncMock, patch
from app.services.coach import generate_and_audit_hint
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.services.llm import LLMClient, LLMResponse

@pytest.mark.asyncio
async def test_tier2_hard_gate_rejects_and_regenerates():
    """Verify that reveals_full_solution=True triggers regeneration and passes when attempt 2 is clean."""
    mock_llm = LLMClient()
    mock_llm.provider = "mock"

    problem = Problem(id=1, platform="codeforces", platform_id="test_1", title="Test Problem")
    knowledge = ProblemKnowledge(
        problem_id=1,
        source_type="official_editorial",
        extraction_method="heading_match",
        validation_status="user_verified",
        techniques=["binary search"]
    )

    call_count = {"judge": 0, "hint": 0}

    async def fake_judge(*args, **kwargs):
        call_count["judge"] += 1
        if call_count["judge"] == 1:
            return {
                "reveals_full_solution": True,
                "contains_executable_code": False,
                "exceeds_level_guidance": False,
                "lacks_problem_context": False,
                "is_vacuous": False,
            }
        else:
            return {
                "reveals_full_solution": False,
                "contains_executable_code": False,
                "exceeds_level_guidance": False,
                "lacks_problem_context": False,
                "is_vacuous": False,
            }

    async def fake_hint(*args, **kwargs):
        call_count["hint"] += 1
        if kwargs.get("rejection_reason"):
            return "Consider binary search on answer without derivation.", False
        return "Here is the full solution: x = 42.", False

    with patch("app.services.coach.evaluate_tier2_judge", side_effect=fake_judge):
        with patch("app.services.coach.generate_hint", side_effect=fake_hint):
            hint_text, tier1_blocked, checklist = await generate_and_audit_hint(
                llm_client=mock_llm,
                target_level=3,
                coach_mode="full_coach",
                problem=problem,
                knowledge=knowledge,
                dialog_history=[],
                user_message="give me a hint",
                session_id=19,
            )

            assert call_count["judge"] == 2
            assert call_count["hint"] == 2
            assert checklist["reveals_full_solution"] is False
            assert "Consider binary search" in hint_text


@pytest.mark.asyncio
async def test_tier2_hard_gate_falls_back_after_two_rejections():
    """Verify that if regeneration still leaks twice, fallback safe response is used."""
    mock_llm = LLMClient()
    mock_llm.provider = "mock"

    problem = Problem(id=1, platform="codeforces", platform_id="test_1", title="Test Problem")
    knowledge = ProblemKnowledge(
        problem_id=1,
        source_type="official_editorial",
        extraction_method="heading_match",
        validation_status="user_verified",
        techniques=["binary search"]
    )

    async def persistent_leak_judge(*args, **kwargs):
        return {
            "reveals_full_solution": True,
            "contains_executable_code": False,
            "exceeds_level_guidance": False,
            "lacks_problem_context": False,
            "is_vacuous": False,
        }

    async def leaky_hint(*args, **kwargs):
        return "Leaked full solution again", False

    with patch("app.services.coach.evaluate_tier2_judge", side_effect=persistent_leak_judge):
        with patch("app.services.coach.generate_hint", side_effect=leaky_hint):
            hint_text, tier1_blocked, checklist = await generate_and_audit_hint(
                llm_client=mock_llm,
                target_level=3,
                coach_mode="full_coach",
                problem=problem,
                knowledge=knowledge,
                dialog_history=[],
                user_message="give me a hint",
                session_id=19,
            )

            assert checklist["reveals_full_solution"] is False
            assert hint_text == "You're very close — try formalizing the specific data structure or technique name only, without deriving the full algorithm yet."
