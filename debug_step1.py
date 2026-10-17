import asyncio
from sqlalchemy import text
from app.database import async_session_factory, engine


async def main():
    async with async_session_factory() as db:
        link = (await db.execute(text("""
            SELECT id, user_id, platform, handle,
                   auth_token IS NOT NULL AS has_token,
                   sync_status, sync_error, last_synced_at
            FROM platform_links WHERE id = 65;
        """))).mappings().all()
        print("=== platform_links id=65 ===")
        for r in link:
            print(dict(r))
        if not link:
            print("(no row)")
            return
        uid = link[0]["user_id"]
        print(f"\n=== using user_id={uid} ===")
        queries = {
            "submissions_total": "SELECT COUNT(*) FROM submissions WHERE user_id = :uid",
            "submissions_ok": "SELECT COUNT(*) FROM submissions WHERE user_id = :uid AND verdict = 'OK'",
            "contest_performances": "SELECT COUNT(*) FROM contest_performances WHERE user_id = :uid",
            "user_analytics": "SELECT user_id, total_problems_solved, total_submissions, computed_at FROM user_analytics WHERE user_id = :uid",
            "all_links_for_user": "SELECT id, platform, handle, sync_status, last_synced_at FROM platform_links WHERE user_id = :uid",
            "verdict_breakdown": "SELECT platform, verdict, COUNT(*) FROM submissions WHERE user_id = :uid GROUP BY platform, verdict ORDER BY platform, verdict",
        }
        for name, q in queries.items():
            rows = (await db.execute(text(q), {"uid": uid})).mappings().all()
            print(f"\n=== {name} ===")
            for r in rows:
                print(dict(r))
            if not rows:
                print("(no rows)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
