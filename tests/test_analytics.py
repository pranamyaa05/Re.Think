"""Unit tests for the Phase 2 AnalyticsService algorithms."""

from datetime import datetime, timedelta, timezone
from app.models.contest_performance import ContestPerformance
from app.models.problem import Problem
from app.models.submission import Submission
from app.services.analytics import AnalyticsService, calculate_median, get_rating_bucket


def test_calculate_median():
    assert calculate_median([]) is None
    assert calculate_median([1500]) == 1500
    assert calculate_median([1200, 1400, 1600]) == 1400
    # Even count: mean of 1400 and 1600 is 1500
    assert calculate_median([1200, 1400, 1600, 1800]) == 1500
    # Even count rounding
    assert calculate_median([1000, 1100]) == 1050


def test_rating_buckets():
    assert get_rating_bucket(None) == "unrated"
    assert get_rating_bucket(800) == "800-999"
    assert get_rating_bucket(1100) == "1000-1199"
    assert get_rating_bucket(1750) == "1600-1799"
    assert get_rating_bucket(2400) == "2400+"
    assert get_rating_bucket(3000) == "2400+"


def test_pre_ac_submission_cutoff():
    """Verify that post-solve submissions are excluded from efficiency and attempt counts."""
    service = AnalyticsService()
    now = datetime.now(timezone.utc)

    prob = Problem(id=1, platform="codeforces", platform_id="1000_A", title="P1", rating=1500, tags=["dp"])
    
    # 2 pre-AC submissions (WA, then AC)
    sub1 = Submission(
        id=101, user_id=1, problem_id=1, platform="codeforces", platform_sub_id=1001,
        verdict="WRONG_ANSWER", submitted_at=now - timedelta(hours=3)
    )
    sub2 = Submission(
        id=102, user_id=1, problem_id=1, platform="codeforces", platform_sub_id=1002,
        verdict="OK", submitted_at=now - timedelta(hours=2)
    )
    # 2 post-AC submissions (e.g. testing alternative solutions)
    sub3 = Submission(
        id=103, user_id=1, problem_id=1, platform="codeforces", platform_sub_id=1003,
        verdict="WRONG_ANSWER", submitted_at=now - timedelta(hours=1)
    )
    sub4 = Submission(
        id=104, user_id=1, problem_id=1, platform="codeforces", platform_sub_id=1004,
        verdict="OK", submitted_at=now
    )

    rows = [(sub1, prob), (sub2, prob), (sub3, prob), (sub4, prob)]
    metrics = service._compute_metrics(rows, [])

    # Total submissions in DB is 4
    assert metrics["total_submissions"] == 4
    assert metrics["total_problems_solved"] == 1
    assert metrics["total_problems_attempted"] == 1

    dp_metrics = metrics["topic_metrics"]["dp"]
    # attempts_to_solve must only count sub1 and sub2 (2 attempts), ignoring sub3 & sub4
    assert dp_metrics["avg_attempts_per_solve"] == 2.0
    # Efficiency: 1 solve / 2 pre-AC attempts = 0.5
    assert dp_metrics["submission_efficiency"] == 0.5


def test_confidence_and_sample_size_gating():
    """Verify sample size thresholds (<3 is None, 3-4 is low_confidence, >=5 is confident)."""
    service = AnalyticsService()
    now = datetime.now(timezone.utc)

    # 1. Topic with 2 solves (<3)
    p1 = Problem(id=1, platform="codeforces", platform_id="1_A", title="P1", rating=1200, tags=["graphs"])
    p2 = Problem(id=2, platform="codeforces", platform_id="1_B", title="P2", rating=1400, tags=["graphs"])
    s1 = Submission(id=1, user_id=1, problem_id=1, platform="codeforces", platform_sub_id=11, verdict="OK", submitted_at=now)
    s2 = Submission(id=2, user_id=1, problem_id=2, platform="codeforces", platform_sub_id=12, verdict="OK", submitted_at=now)

    res2 = service._compute_metrics([(s1, p1), (s2, p2)], [])
    g2 = res2["topic_metrics"]["graphs"]
    assert g2["demonstrated_level"] is None
    assert g2["confident"] is False
    assert g2["low_confidence"] is False

    # 2. Topic with 3 solves (3-4 -> low_confidence = True)
    p3 = Problem(id=3, platform="codeforces", platform_id="1_C", title="P3", rating=1600, tags=["graphs"])
    s3 = Submission(id=3, user_id=1, problem_id=3, platform="codeforces", platform_sub_id=13, verdict="OK", submitted_at=now)

    res3 = service._compute_metrics([(s1, p1), (s2, p2), (s3, p3)], [])
    g3 = res3["topic_metrics"]["graphs"]
    assert g3["demonstrated_level"] == 1400  # median(1200, 1400, 1600)
    assert g3["confident"] is False
    assert g3["low_confidence"] is True

    # 3. Topic with 5 solves (>=5 -> confident = True)
    p4 = Problem(id=4, platform="codeforces", platform_id="1_D", title="P4", rating=1800, tags=["graphs"])
    p5 = Problem(id=5, platform="codeforces", platform_id="1_E", title="P5", rating=2000, tags=["graphs"])
    s4 = Submission(id=4, user_id=1, problem_id=4, platform="codeforces", platform_sub_id=14, verdict="OK", submitted_at=now)
    s5 = Submission(id=5, user_id=1, problem_id=5, platform="codeforces", platform_sub_id=15, verdict="OK", submitted_at=now)

    res5 = service._compute_metrics([(s1, p1), (s2, p2), (s3, p3), (s4, p4), (s5, p5)], [])
    g5 = res5["topic_metrics"]["graphs"]
    assert g5["demonstrated_level"] == 1600  # median(1200, 1400, 1600, 1800, 2000)
    assert g5["confident"] is True
    assert g5["low_confidence"] is False


def test_weakness_requires_minimum_attempts():
    """Verify that a topic is NOT flagged as a weakness for low completion rate if attempts < 5."""
    service = AnalyticsService()
    now = datetime.now(timezone.utc)

    # Topic 'geometry': 4 attempts, 1 solve (completion rate = 25%)
    # Because attempts = 4 < 5, it should NOT be flagged as weakness.
    rows_under_5 = []
    for i in range(4):
        p = Problem(id=i + 1, platform="codeforces", platform_id=f"2_{i}", title=f"Geo{i}", rating=1500, tags=["geometry"])
        verdict = "OK" if i == 0 else "WRONG_ANSWER"
        s = Submission(id=i + 1, user_id=1, problem_id=p.id, platform="codeforces", platform_sub_id=200 + i, verdict=verdict, submitted_at=now)
        rows_under_5.append((s, p))

    res_under_5 = service._compute_metrics(rows_under_5, [])
    assert "geometry" not in res_under_5["weaknesses"]

    # Now add 5th attempt (WA) -> attempts = 5 >= 5, 1 solve (20% completion rate)
    p5 = Problem(id=5, platform="codeforces", platform_id="2_5", title="Geo5", rating=1500, tags=["geometry"])
    s5 = Submission(id=5, user_id=1, problem_id=5, platform="codeforces", platform_sub_id=205, verdict="WRONG_ANSWER", submitted_at=now)
    rows_at_5 = rows_under_5 + [(s5, p5)]

    res_at_5 = service._compute_metrics(rows_at_5, [])
    assert "geometry" in res_at_5["weaknesses"]


def test_contest_volatility_calculation():
    """Verify contest metrics, rating delta and volatility."""
    service = AnalyticsService()
    now = datetime.now(timezone.utc)

    c1 = ContestPerformance(id=1, user_id=1, platform="codeforces", contest_id=101, contest_name="R1",
                            rating_before=1500, rating_after=1550, rank=300, contest_date=now - timedelta(days=20))  # delta +50
    c2 = ContestPerformance(id=2, user_id=1, platform="codeforces", contest_id=102, contest_name="R2",
                            rating_before=1550, rating_after=1530, rank=800, contest_date=now - timedelta(days=10))  # delta -20
    c3 = ContestPerformance(id=3, user_id=1, platform="codeforces", contest_id=103, contest_name="R3",
                            rating_before=1530, rating_after=1620, rank=150, contest_date=now - timedelta(days=2))   # delta +90

    res = service._compute_metrics([], [c1, c2, c3])
    cm = res["contest_metrics"]

    assert cm["current_rating"] == 1620
    assert cm["max_rating"] == 1620
    assert cm["best_rank"] == 150
    assert cm["contest_count"] == 3
    # deltas: 50, -20, 90. mean = 40.0
    assert cm["avg_delta"] == 40.0
    # variance = ((50-40)^2 + (-20-40)^2 + (90-40)^2) / 3 = (100 + 3600 + 2500) / 3 = 6200 / 3 = 2066.666...
    # stddev = sqrt(2066.666...) ≈ 45.46 -> 45.5
    assert cm["rating_volatility"] == 45.5
