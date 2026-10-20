"""API Key and identity authentication dependencies.

Two layers protect the API:

* ``verify_api_key`` — the shared key is held only by the frontend's server
  process, never by the browser.
* ``get_verified_identity`` / ``require_user_scope`` — the frontend server
  forwards the OAuth identity it verified in the ``X-External-Id`` header.
  A request for ``user_id`` is only allowed when that identity maps to it,
  so a logged-in user can never read or mutate another user's data.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User


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


async def get_verified_identity(
    x_external_id: Optional[str] = Header(None, alias="X-External-Id"),
) -> str:
    """The OAuth identity verified by the frontend server for this request."""
    if not x_external_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verified identity header X-External-Id is required",
        )
    return x_external_id


async def require_user_scope(
    user_id: int,
    external_id: str = Depends(get_verified_identity),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Allow the request only when ``external_id`` maps to ``user_id``.

    ``user_id`` is bound from the path or query parameter of the route that
    declares this dependency, so ownership is enforced before the handler
    body runs.
    """
    result = await db.execute(select(User).where(User.external_id == external_id))
    user = result.scalar_one_or_none()
    if user is None or user.id != user_id:
        # 403 for an identity that maps to another user; 404 when the identity
        # is unknown entirely (no leak about which ids exist).
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Identity is not mapped to a backend user",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this user",
        )
    return user


async def assert_link_owner(
    db: AsyncSession, external_id: str, link
) -> User:
    """Raise 403 unless the identity owns the platform-link's user."""
    result = await db.execute(select(User).where(User.external_id == external_id))
    user = result.scalar_one_or_none()
    if user is None or link is None or user.id != link.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: identity does not own this platform link",
        )
    return user
