import asyncio
from sqlalchemy import text
from app.database import async_session_factory

async def query_llm_log():
    async with async_session_factory() as db:
        res = await db.execute(text("SELECT id, session_id, caller, model, tokens_in, tokens_out, latency_ms FROM llm_call_log ORDER BY id DESC LIMIT 20;"))
        rows = res.mappings().all()
        print("=== LLM_CALL_LOG (LAST 20) ===")
        print(f"| {'id':<4} | {'session_id':<10} | {'caller':<20} | {'model':<18} | {'tokens_in':<10} | {'tokens_out':<10} | {'latency_ms':<10} |")
        print("|" + "-"*6 + "|" + "-"*12 + "|" + "-"*22 + "|" + "-"*20 + "|" + "-"*12 + "|" + "-"*12 + "|" + "-"*12 + "|")
        for r in rows:
            sid = str(r['session_id']) if r['session_id'] is not None else "None"
            print(f"| {r['id']:<4} | {sid:<10} | {r['caller']:<20} | {r['model']:<18} | {r['tokens_in']:<10} | {r['tokens_out']:<10} | {r['latency_ms']:<10} |")

async def query_session_messages(session_id: int):
    async with async_session_factory() as db:
        res = await db.execute(
            text("SELECT id, hint_level, role, content, leakage_checklist, tier1_blocked FROM hint_messages WHERE session_id = :sid ORDER BY created_at;"),
            {"sid": session_id}
        )
        rows = res.mappings().all()
        print(f"\n=== HINT_MESSAGES FOR SESSION {session_id} ===")
        for r in rows:
            print(f"\n[Message ID {r['id']}] role={r['role']} | level={r['hint_level']} | tier1_blocked={r['tier1_blocked']}")
            print(f"leakage_checklist: {r['leakage_checklist']}")
            print(f"content:\n{r['content']}")

async def main():
    try:
        await query_llm_log()
        await query_session_messages(13)
    finally:
        from app.database import engine
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
