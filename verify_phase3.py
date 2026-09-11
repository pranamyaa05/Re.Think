"""
Phase 3 Verification Script:
Verifies Editorial Preprocessing, Extraction Pipeline, Categorical Trust Matrix,
Dual-Step Socratic Coaching, Code Snapshot Tracking, Guardrails, and Database Traceability
against live PostgreSQL database.
"""

import asyncio
import json
import logging
import sys
from sqlalchemy import select, text

from app.database import async_session_factory, engine
from app.models.hint_message import HintMessage
from app.models.hint_session import HintSession
from app.models.llm_call_log import LLMCallLog
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.models.user import User
from app.services.coach import CoachService
from app.services.editorial import (
    EditorialService,
    clean_editorial_html,
    extract_problem_section_by_heading,
    resolve_coach_mode,
)
from app.services.llm import LLMClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_phase3")

BANNED_TONE_PHRASES = [
    "i cannot give you the solution",
    "as an ai coach",
    "i am only allowed to",
    "my goal is to guide you",
    "let's take it step by step",
]


async def run_verification():
    print("=" * 70)
    print("PHASE 3 VERIFICATION: EDITORIAL KNOWLEDGE & SOCRATIC COACH")
    print("=" * 70)

    # --------------------------------------------------------------------------
    # 1. Select a real problem and user from PostgreSQL
    # --------------------------------------------------------------------------
    async with async_session_factory() as db:
        prob_res = await db.execute(
            select(Problem).where(Problem.rating.isnot(None)).order_by(Problem.id.asc()).limit(1)
        )
        problem = prob_res.scalar_one_or_none()
        assert problem is not None, "At least one problem must exist in database"

        user_res = await db.execute(select(User).order_by(User.id.asc()).limit(1))
        user = user_res.scalar_one_or_none()
        assert user is not None, "At least one user must exist in database"

        problem_id = problem.id
        user_id = user.id

    print(f"\n[Step 1] Target Problem: ID={problem_id}, Platform_ID='{problem.platform_id}', Title='{problem.title}'")
    print(f"         Target User:    ID={user_id}, Username='{user.username}'")

    # --------------------------------------------------------------------------
    # 2. Editorial Preprocessing & Extraction Pipeline
    # --------------------------------------------------------------------------
    raw_editorial_html = f"""
    <div class="problem-statement">
        <h3>Problem {problem.problem_index or 'A'}. {problem.title}</h3>
        <p>In this problem, we need to optimize the selection criteria under constraint $N \\le 2 \\cdot 10^5$.</p>
        <p>Consider the cumulative sum equation: $$S(i) = \\sum_{{k=1}}^i A_k$$</p>
        <p>Notice that the prefix sums are monotonically non-decreasing when elements are non-negative.</p>
        <pre><code class="cpp">
        #include &lt;iostream&gt;
        #include &lt;vector&gt;
        using namespace std;
        int main() {{
            int n; cin >> n;
            vector&lt;int&gt; a(n);
            return 0;
        }}
        </code></pre>
        <p>By binary searching over the prefix sums, we achieve an overall complexity of $O(N \\log N)$.</p>
    </div>
    """

    cleaned_html = clean_editorial_html(raw_editorial_html)

    # Invariant: Author code is stripped
    assert "#include" not in cleaned_html, "Author code must be stripped"
    assert "using namespace std" not in cleaned_html, "Author code must be stripped"
    assert "[Solution code omitted]" in cleaned_html, "Placeholder must be inserted"

    # Invariant: MathJax is preserved
    assert r"$N \le 2 \cdot 10^5$" in cleaned_html, "Inline MathJax must be preserved"
    assert r"$$S(i) = \sum_{k=1}^i A_k$$" in cleaned_html, "Display MathJax must be preserved"
    print("\n[Step 2] Editorial HTML Preprocessing Verified:")
    print("         - Author C++ solution code successfully stripped.")
    print("         - MathJax inline and display formulas preserved.")

    # Ingest editorial into ProblemKnowledge
    llm_client = LLMClient(provider="mock")
    editorial_service = EditorialService(llm_client=llm_client)

    knowledge = await editorial_service.ingest_editorial(
        problem_id=problem_id,
        raw_editorial=raw_editorial_html,
        editorial_url="https://codeforces.com/blog/entry/99999",
    )
    assert knowledge.problem_id == problem_id
    assert knowledge.source_type == "official_editorial"
    assert knowledge.extraction_method == "heading_match"
    assert knowledge.validation_status == "unchecked"
    assert resolve_coach_mode(knowledge) == "cautious_coach"
    print("\n[Step 3] Knowledge Ingestion Verified:")
    print(f"         - Ingestion Method: {knowledge.extraction_method}")
    print(f"         - Validation Status: {knowledge.validation_status}")
    print(f"         - Initial Coach Mode: {resolve_coach_mode(knowledge)}")

    # --------------------------------------------------------------------------
    # 3. Categorical Trust Transition: Verify Knowledge
    # --------------------------------------------------------------------------
    async with async_session_factory() as db:
        k_rec = (await db.execute(
            select(ProblemKnowledge).where(ProblemKnowledge.id == knowledge.id)
        )).scalar_one()
        k_rec.validation_status = "user_verified"
        await db.commit()
        await db.refresh(k_rec)
        coach_mode_after = resolve_coach_mode(k_rec)

    assert coach_mode_after == "full_coach", "Verified official editorial must map to full_coach"
    print(f"\n[Step 4] Trust Matrix Transition Verified: unchecked -> user_verified => {coach_mode_after}")

    # --------------------------------------------------------------------------
    # 4. Coaching Session Lifecycle: Multi-Turn Dialog & Code Snapshots
    # --------------------------------------------------------------------------
    coach_service = CoachService(llm_client=llm_client)

    # Turn 0: Session Creation & Initial L0 Diagnostic Question
    session = await coach_service.create_session(user_id=user_id, problem_id=problem_id)
    session_id = session.id
    assert session.current_level == 0
    assert session.coach_mode == "full_coach"
    assert session.outcome == "ongoing"
    assert len(session.messages) == 1

    turn0_msg = session.messages[0]
    assert turn0_msg.role == "coach"
    assert turn0_msg.hint_level == 0
    assert turn0_msg.tier1_blocked is False
    assert turn0_msg.leakage_checklist is not None

    # Verify Non-Patronizing Tone
    content_lower = turn0_msg.content.lower()
    for phrase in BANNED_TONE_PHRASES:
        assert phrase not in content_lower, f"Banned patronizing phrase '{phrase}' found in coach hint"

    print(f"\n[Step 5] Coaching Session Created (ID={session_id}):")
    print(f"         - Level: {session.current_level} (L0 Diagnostic)")
    print(f"         - Initial Coach Hint: \"{turn0_msg.content[:80]}...\"")
    print(f"         - Tier 1 Blocked: {turn0_msg.tier1_blocked}")
    print(f"         - Tier 2 Shadow Checklist: {turn0_msg.leakage_checklist}")

    # Turn 1: User replies with observation + Code Draft
    user_code_v1 = """def solve():
    n = int(input())
    a = list(map(int, input().split()))
    # Trying naive O(N^2) search
    ans = 0
    for i in range(n):
        for j in range(i, n):
            ans += a[i]
    return ans
"""
    coach_reply1, session = await coach_service.process_user_message(
        session_id=session_id,
        user_message="An O(N^2) double loop is too slow for N=2e5. Does the prefix sum monotonicity help?",
        current_code=user_code_v1,
    )
    assert coach_reply1.role == "coach"
    assert session.current_level >= 1
    assert coach_reply1.tier1_blocked is False
    print(f"\n[Step 6] Turn 1 Completed:")
    print(f"         - User submitted code snapshot ({len(user_code_v1)} bytes)")
    print(f"         - FSM Evaluator transitioned level: 0 -> {session.current_level}")
    print(f"         - Coach Reply: \"{coach_reply1.content[:80]}...\"")

    # Turn 2: User requests escalation
    coach_reply2, session = await coach_service.process_user_message(
        session_id=session_id,
        user_message="I see the monotonicity. What standard algorithm paradigm fits this?",
        request_escalation=True,
    )
    assert coach_reply2.role == "coach"
    assert session.current_level >= 2
    print(f"\n[Step 7] Turn 2 Completed (Escalation):")
    print(f"         - Escalated level to: {session.current_level}")
    print(f"         - Coach Algorithmic Direction: \"{coach_reply2.content[:80]}...\"")

    # Conclude session as solved
    concluded_session = await coach_service.conclude_session(session_id=session_id, outcome="solved")
    assert concluded_session.outcome == "solved"
    assert concluded_session.solved_at is not None
    print(f"\n[Step 8] Session Concluded:")
    print(f"         - Outcome: {concluded_session.outcome}")
    print(f"         - Solved At: {concluded_session.solved_at}")

    # --------------------------------------------------------------------------
    # 5. Direct SQL Invariant Audit
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("DIRECT SQL INVARIANT AUDIT")
    print("=" * 70)

    async with async_session_factory() as db:
        # Audit hint_sessions row
        sess_row = (await db.execute(
            text("SELECT id, user_id, problem_id, current_level, coach_mode, outcome, solved_at FROM hint_sessions WHERE id = :sid"),
            {"sid": session_id}
        )).mappings().one()
        print(f"SQL > hint_sessions: ID={sess_row['id']}, Level={sess_row['current_level']}, Mode='{sess_row['coach_mode']}', Outcome='{sess_row['outcome']}'")

        # Audit hint_messages rows
        msg_rows = (await db.execute(
            text("SELECT id, role, hint_level, code_snapshot IS NOT NULL as has_code, tier1_blocked, leakage_checklist FROM hint_messages WHERE session_id = :sid ORDER BY created_at ASC"),
            {"sid": session_id}
        )).mappings().all()

        print(f"\nSQL > hint_messages ({len(msg_rows)} rows):")
        user_code_saved = False
        for r in msg_rows:
            print(f"      - ID={r['id']}: role='{r['role']}', level={r['hint_level']}, has_code={r['has_code']}, blocked={r['tier1_blocked']}")
            if r["has_code"]:
                user_code_saved = True

        assert user_code_saved, "At least one user message must have persisted code_snapshot in DB"

        # Audit llm_call_log rows for session traceability
        llm_rows = (await db.execute(
            text("SELECT id, session_id, caller, model, latency_ms FROM llm_call_log WHERE session_id = :sid ORDER BY created_at ASC"),
            {"sid": session_id}
        )).mappings().all()

        print(f"\nSQL > llm_call_log with session_id={session_id} ({len(llm_rows)} calls logged):")
        callers = set()
        for r in llm_rows:
            print(f"      - Call ID={r['id']}: caller='{r['caller']}', model='{r['model']}', latency={r['latency_ms']}ms")
            callers.add(r["caller"])

        assert "hint_generator" in callers, "hint_generator calls must be logged with session_id"
        assert "judge" in callers, "judge calls must be logged with session_id"
        assert "fsm_evaluator" in callers, "fsm_evaluator calls must be logged with session_id"

    print("\n" + "=" * 70)
    print("ALL PHASE 3 INVARIANTS AND AUDITS PASSED CLEANLY (Code 0)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_verification())
