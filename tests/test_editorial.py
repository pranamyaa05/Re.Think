"""Unit tests for EditorialService preprocessing, heading match, and coach mode resolution."""

import pytest
from app.database import async_session_factory, engine
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.services.editorial import (
    clean_editorial_html,
    extract_problem_section_by_heading,
    resolve_coach_mode,
    EditorialService,
)
from app.services.llm import LLMClient


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()


def test_clean_editorial_html():
    raw_html = """
    <div>
        <h2>Problem A: Subarray Sum</h2>
        <p>The problem asks us to find a subarray with maximum sum in $O(N)$ time.</p>
        <p>Consider the formula: $$dp[i] = \\max(a[i], dp[i-1] + a[i])$$</p>
        <pre><code class="cpp">
        #include &lt;iostream&gt;
        int main() {
            int n; cin >> n;
            return 0;
        }
        </code></pre>
        <script>console.log('malicious');</script>
    </div>
    """
    cleaned = clean_editorial_html(raw_html)

    # 1. Solution code is stripped
    assert "#include" not in cleaned
    assert "int main()" not in cleaned
    assert "[Solution code omitted]" in cleaned

    # 2. MathJax equations are preserved
    assert "$O(N)$" in cleaned
    assert "$$dp[i] = \\max(a[i], dp[i-1] + a[i])$$" in cleaned

    # 3. Scripts are removed
    assert "console.log" not in cleaned


def test_extract_problem_section_by_heading_standard():
    html_doc = """
    <h3>Problem A. Watermelon</h3>
    <p>Divide the watermelon into two parts of even weight. If w is even and greater than 2, output YES.</p>
    <h3>Problem B. Before an Exam</h3>
    <p>Distribute the study hours greedily across days.</p>
    """
    sec_a = extract_problem_section_by_heading(html_doc, "A", "Watermelon")
    assert sec_a is not None
    assert "Divide the watermelon" in sec_a
    assert "Distribute the study hours" not in sec_a

    sec_b = extract_problem_section_by_heading(html_doc, "B", "Before an Exam")
    assert sec_b is not None
    assert "Distribute the study hours" in sec_b
    assert "Divide the watermelon" not in sec_b


def test_extract_problem_section_by_heading_combined():
    html_doc = """
    <h2>Problem A. Easy Task</h2>
    <p>This is problem A text that describes the solution in detail so that it exceeds eighty characters.</p>
    <h2>Problems C1 and C2. Permutation Game</h2>
    <p>Notice that the winner is determined by parity of cycles. The state can be reduced to a bipartite graph matching.</p>
    <h2>Problem D. Final Problem</h2>
    <p>This is problem D text describing segment tree point updates and range query algorithms.</p>
    """
    # Both C1 and C2 should successfully extract the combined section
    sec_c1 = extract_problem_section_by_heading(html_doc, "C1")
    assert sec_c1 is not None
    assert "Permutation Game" in sec_c1
    assert "winner is determined by parity" in sec_c1
    assert "Problem D" not in sec_c1

    sec_c2 = extract_problem_section_by_heading(html_doc, "C2")
    assert sec_c2 is not None
    assert "Permutation Game" in sec_c2


def test_resolve_coach_mode_categorical():
    # 1. Authoritative + verified -> full_coach
    k1 = ProblemKnowledge(
        problem_id=1,
        source_type="official_editorial",
        extraction_method="heading_match",
        validation_status="user_verified",
    )
    assert resolve_coach_mode(k1) == "full_coach"

    # 2. Authoritative + unverified -> cautious_coach
    k2 = ProblemKnowledge(
        problem_id=1,
        source_type="official_editorial",
        extraction_method="heading_match",
        validation_status="unchecked",
    )
    assert resolve_coach_mode(k2) == "cautious_coach"

    # 3. LLM-extracted -> peer_mode (never full or cautious)
    k3 = ProblemKnowledge(
        problem_id=1,
        source_type="official_editorial",
        extraction_method="llm_parsed",
        validation_status="user_verified",
    )
    assert resolve_coach_mode(k3) == "peer_mode"

    # 4. LLM-generated -> peer_mode
    k4 = ProblemKnowledge(
        problem_id=1,
        source_type="llm_generated",
        extraction_method="manual",
        validation_status="user_verified",
    )
    assert resolve_coach_mode(k4) == "peer_mode"

    # 5. Rejected by user -> peer_mode
    k5 = ProblemKnowledge(
        problem_id=1,
        source_type="official_editorial",
        extraction_method="heading_match",
        validation_status="user_rejected",
    )
    assert resolve_coach_mode(k5) == "peer_mode"

    # 6. No knowledge -> peer_mode
    assert resolve_coach_mode(None) == "peer_mode"


import uuid


@pytest.mark.asyncio
async def test_ingest_editorial_end_to_end():
    # Seed a problem in DB with unique platform_id
    test_pid = f"9999_{uuid.uuid4().hex[:6]}"
    async with async_session_factory() as session:
        prob = Problem(
            platform="codeforces",
            platform_id=test_pid,
            title="Greedy Intervals",
            rating=1400,
            problem_index="A",
            tags=["greedy", "sortings"],
        )
        session.add(prob)
        await session.commit()
        prob_id = prob.id

    raw_html = """
    <h3>Problem A. Greedy Intervals</h3>
    <p>To maximize non-overlapping intervals, sort all segments by their finish time.
    Pick the earliest finishing segment and eliminate overlapping segments.</p>
    """

    service = EditorialService(llm_client=LLMClient(provider="mock"))
    knowledge = await service.ingest_editorial(prob_id, raw_html, editorial_url="https://codeforces.com/blog/entry/12345")

    assert knowledge.problem_id == prob_id
    assert knowledge.source_type == "official_editorial"
    assert knowledge.extraction_method == "heading_match"
    assert knowledge.validation_status == "unchecked"
    assert len(knowledge.techniques) > 0
    assert resolve_coach_mode(knowledge) == "cautious_coach"
