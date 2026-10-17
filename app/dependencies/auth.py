"""API Key authentication dependency."""

from typing import Optional
from fastapi import Header, HTTPException, status
from app.config import settings


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> str:
    """
    Validates the X-API-Key header against the configured API_KEY in settings.
    Returns 401 with a clean JSON error on missing or mismatched key.
    """
    configured_key = settings.api_key
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server API key is not configured.",
        )

    if not x_api_key or x_api_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return x_api_key
