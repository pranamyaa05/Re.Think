"""Live end-to-end verification script for Phase 1 Codeforces sync."""

import asyncio
import httpx


async def main():
    base_url = "http://127.0.0.1:8000"
    # Using 'tourist' or any active handle to test live sync
    test_handle = "tourist"

    async with httpx.AsyncClient(base_url=base_url, timeout=180.0) as client:
        print("1. Creating user...")
        import uuid
        username = f"e2e_{uuid.uuid4().hex[:8]}"
        u_res = await client.post("/api/users", json={"username": username})
        assert u_res.status_code == 201, f"Create user failed: {u_res.text}"
        user = u_res.json()
        user_id = user["id"]
        print(f"Created user id={user_id}, username={user['username']}")

        print(f"2. Linking Codeforces handle '{test_handle}'...")
        l_res = await client.post(
            "/api/platforms/link",
            json={"user_id": user_id, "platform": "codeforces", "handle": test_handle},
        )
        assert l_res.status_code == 201, f"Link failed: {l_res.text}"
        link = l_res.json()
        link_id = link["id"]
        print(f"Linked handle with link_id={link_id}")

        print("3. Triggering initial sync (this will fetch submissions and contests from CF API)...")
        sync_res = await client.post(f"/api/platforms/{link_id}/sync")
        assert sync_res.status_code == 200, f"Sync failed: {sync_res.text}"
        stats = sync_res.json()
        print("Sync completed successfully!")
        print(f"  - Submissions synced: {stats['submissions_synced']}")
        print(f"  - Contests synced: {stats['contests_synced']}")
        print(f"  - Problems upserted: {stats['problems_upserted']}")

        # Truncation Detection: A handle like 'tourist' has > 5000 submissions.
        # If it stops at exactly 1000 (10 pages * 100), the old 10-page bug is present!
        assert stats["submissions_synced"] != 1000, (
            "ERROR: Silent history truncation detected! Submissions synced is exactly 1000, "
            "indicating an arbitrary 10-page limit cap."
        )
        if test_handle == "tourist":
            assert stats["submissions_synced"] > 1000, (
                f"ERROR: Expected > 1000 submissions for '{test_handle}', but got {stats['submissions_synced']}."
            )
            print(f"  Truncation check passed: Synced {stats['submissions_synced']} (> 1000) without artificial page capping.")

        print("\n3b. Testing incremental sync (stop-on-overlap verification)...")
        sync_res_2 = await client.post(f"/api/platforms/{link_id}/sync")
        assert sync_res_2.status_code == 200, f"Incremental sync failed: {sync_res_2.text}"
        stats_2 = sync_res_2.json()
        assert stats_2["submissions_synced"] == 0, (
            f"ERROR: Incremental sync did not stop on overlap! Synced {stats_2['submissions_synced']} submissions."
        )
        print("  Stop-on-overlap passed: 0 new submissions on immediate re-sync.")

        print("4. Querying stored submissions...")
        subs_res = await client.get("/api/submissions", params={"user_id": user_id, "limit": 5})
        assert subs_res.status_code == 200
        subs = subs_res.json()
        print(f"Retrieved {len(subs)} latest submissions from DB:")
        for s in subs:
            print(f"  • Submission {s['platform_sub_id']}: verdict={s['verdict']}, lang={s['language']}")

        print("5. Querying stored contest rating changes...")
        contests_res = await client.get("/api/contests", params={"user_id": user_id, "limit": 5})
        assert contests_res.status_code == 200
        contests = contests_res.json()
        print(f"Retrieved {len(contests)} contest performances from DB:")
        for c in contests:
            print(f"  • Contest {c['contest_id']} ({c['contest_name']}): {c['rating_before']} -> {c['rating_after']} (rank {c['rank']})")

        print("6. Querying problems...")
        prob_res = await client.get("/api/problems", params={"limit": 5})
        assert prob_res.status_code == 200
        probs = prob_res.json()
        print(f"Retrieved {len(probs)} problems from DB:")
        for p in probs:
            print(f"  • {p['platform_id']}: '{p['title']}', rating={p['rating']}, tags={p['tags']}")

        print("\n ALL PHASE 1 LIVE VERIFICATION CHECKS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
