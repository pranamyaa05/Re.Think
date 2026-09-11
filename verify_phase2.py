"""
Phase 2 Real-Data Verification Script.

Tests the Analytics Engine against real Codeforces submission and contest data:
1. Recomputes analytics via API.
2. Audits summary metrics, completion rate, and submission efficiency.
3. Verifies mathematical invariants on topic demonstrated levels.
4. Checks difficulty distribution bucket sum equals total solved problems.
5. Verifies contest progression, peak rating, and volatility.
"""

import asyncio
import httpx


async def main():
    base_url = "http://127.0.0.1:8000/api"
    # Using User ID 13 (tourist synced in Phase 1)
    user_id = 13

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        print(f"=== Phase 2 Verification: User {user_id} ===")

        # 1. Trigger Recompute
        print("1. Testing POST /api/analytics/{user_id}/recompute ...")
        rec_res = await client.post(f"/analytics/{user_id}/recompute")
        assert rec_res.status_code == 200, f"Recompute failed: {rec_res.text}"
        rec_data = rec_res.json()
        print(f"   Recompute success: Solved={rec_data['total_problems_solved']}, Attempted={rec_data['total_problems_attempted']}")
        print(f"   Strengths: {rec_data['strengths']}")
        print(f"   Weaknesses: {rec_data['weaknesses']}")
        print(f"   Stale Topics: {rec_data['stale_topics']}")

        # 2. Query Summary
        print("\n2. Testing GET /api/analytics/{user_id}/summary ...")
        sum_res = await client.get(f"/analytics/{user_id}/summary")
        assert sum_res.status_code == 200, f"Summary failed: {sum_res.text}"
        summary = sum_res.json()
        assert summary["total_problems_solved"] > 0
        assert summary["total_problems_attempted"] >= summary["total_problems_solved"]
        assert 0.0 <= summary["overall_completion_rate"] <= 1.0
        assert 0.0 <= summary["overall_efficiency"] <= 1.0
        print(f"   Overall Completion Rate: {summary['overall_completion_rate'] * 100:.1f}%")
        print(f"   Overall Submission Efficiency: {summary['overall_efficiency'] * 100:.1f}%")

        # 3. Query Topics with Invariant Auditing
        print("\n3. Testing GET /api/analytics/{user_id}/topics ...")
        top_res = await client.get(f"/analytics/{user_id}/topics?sort_by=level&order=desc")
        assert top_res.status_code == 200, f"Topics failed: {top_res.text}"
        topics = top_res.json()
        assert len(topics) > 0, "No topics returned"
        print(f"   Retrieved {len(topics)} topics. Top 5 demonstrated levels:")
        for t in topics[:5]:
            print(f"   • {t['tag']:<20} | Level: {t['demonstrated_level']} | Freshness: {t['freshness_days']}d | Solved: {t['sample_size']} | Comp: {t['solve_completion_rate']*100:.1f}% | Eff: {t['submission_efficiency']:.2f}")

        # Invariant checks on topics
        for t in topics:
            if t["confident"]:
                assert t["rated_sample_size"] >= 5, f"Topic {t['tag']} marked confident with < 5 rated solves"
                assert not t["low_confidence"]
            elif t["low_confidence"]:
                assert 3 <= t["rated_sample_size"] < 5, f"Topic {t['tag']} marked low_confidence with invalid sample size"
                assert not t["confident"]
            else:
                assert t["demonstrated_level"] is None, f"Topic {t['tag']} has level without meeting sample threshold"

        # 4. Query Difficulty Distribution
        print("\n4. Testing GET /api/analytics/{user_id}/difficulty ...")
        diff_res = await client.get(f"/analytics/{user_id}/difficulty")
        assert diff_res.status_code == 200, f"Difficulty failed: {diff_res.text}"
        diff_data = diff_res.json()
        bucket_sum = sum(b["count"] for b in diff_data["buckets"])
        print(f"   Difficulty buckets sum: {bucket_sum} (Total solved: {summary['total_problems_solved']})")
        assert bucket_sum == summary["total_problems_solved"], "Difficulty distribution sum does not match total problems solved!"
        for b in diff_data["buckets"]:
            if b["count"] > 0:
                print(f"   • {b['rating_range']:<12}: {b['count']} problems")

        # 5. Query Contest Analytics
        print("\n5. Testing GET /api/analytics/{user_id}/contests ...")
        cont_res = await client.get(f"/analytics/{user_id}/contests")
        assert cont_res.status_code == 200, f"Contests failed: {cont_res.text}"
        cont_data = cont_res.json()
        print(f"   Current Rating: {cont_data['current_rating']}, Peak Rating: {cont_data['max_rating']}")
        print(f"   Contest Count: {cont_data['contest_count']}, Best Rank: {cont_data['best_rank']}")
        print(f"   Average Delta: {cont_data['avg_delta']}, Volatility: {cont_data['rating_volatility']}")
        assert cont_data["contest_count"] > 0
        assert cont_data["max_rating"] >= cont_data["current_rating"]
        assert cont_data["rating_volatility"] >= 0.0

        print("\n ALL PHASE 2 REAL-DATA VERIFICATION INVARIANTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
