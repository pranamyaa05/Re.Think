"""Main FastAPI application entrypoint."""

from fastapi import FastAPI
from app.routers import router

app = FastAPI(
    title="Re.Think API",
    description="A competitive programming companion tracking growth with structured insights.",
    version="0.1.0",
)

app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "rethink-api"}
