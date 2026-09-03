"""
Async client adapter for the official Codeforces REST API.

Key design details:
- Respects Codeforces rate limits (configured to 2 req/s by default).
- Uses httpx.AsyncClient with sensible timeouts.
- All requests are strictly outside database transactions.
- Handles API failures and errors cleanly via custom exceptions.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings


class CodeforcesAPIError(Exception):
    """Raised when the Codeforces API returns a non-OK status or network error."""
    pass


class CodeforcesAdapter:
    def __init__(
        self,
        base_url: Optional[str] = None,
        requests_per_second: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.cf_api_base_url).rstrip("/")
        self.min_interval = 1.0 / (requests_per_second or settings.cf_requests_per_second)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def _throttle(self) -> None:
        """Enforces a clean in-memory token/interval rate limit."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_request_time = time.monotonic()

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/{endpoint}"
        max_retries = 4
        backoff = 2.5

        for attempt in range(1, max_retries + 1):
            await self._throttle()
            async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
                try:
                    response = await client.get(url, params=params)
                except httpx.HTTPError as exc:
                    if attempt == max_retries:
                        raise CodeforcesAPIError(f"HTTP request to Codeforces failed: {exc}") from exc
                    await asyncio.sleep(backoff * attempt)
                    continue

                if response.status_code in (502, 503, 504):
                    if attempt == max_retries:
                        raise CodeforcesAPIError(
                            f"Codeforces returned HTTP {response.status_code} (gateway timeout/overload): {response.text[:300]}"
                        )
                    await asyncio.sleep(backoff * attempt)
                    continue

                try:
                    data = response.json()
                except ValueError as exc:
                    raise CodeforcesAPIError(f"Invalid JSON returned by Codeforces API: {exc}") from exc

                if response.status_code != 200:
                    raise CodeforcesAPIError(
                        f"Codeforces returned HTTP {response.status_code}: {response.text[:300]}"
                    )

                if not isinstance(data, dict) or data.get("status") != "OK":
                    comment = data.get("comment", response.text[:300]) if isinstance(data, dict) else response.text[:300]
                    raise CodeforcesAPIError(f"Codeforces API error: {comment}")

                return data.get("result")

    async def get_user_info(self, handle: str) -> Dict[str, Any]:
        """
        Fetch user profile info.
        API endpoint: user.info?handles=<handle>
        """
        result = await self._get("user.info", params={"handles": handle})
        if not result or not isinstance(result, list):
            raise CodeforcesAPIError(f"User {handle} not found")
        return result[0]

    async def get_user_status(
        self, handle: str, from_index: int = 1, count: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch paginated submissions (newest first).
        Note: from_index is a 1-based pagination offset into reverse-chronological submissions.
        API endpoint: user.status?handle=<handle>&from=<from_index>&count=<count>
        """
        result = await self._get(
            "user.status",
            params={"handle": handle, "from": from_index, "count": count},
        )
        return result or []

    async def get_user_rating(self, handle: str) -> List[Dict[str, Any]]:
        """
        Fetch complete contest rating change history for user.
        API endpoint: user.rating?handle=<handle>
        """
        result = await self._get("user.rating", params={"handle": handle})
        return result or []

    async def get_problemset_problems(self) -> Dict[str, Any]:
        """
        Fetch all problems and problem statistics in the problemset.
        API endpoint: problemset.problems
        Returns dict with keys 'problems' and 'problemStatistics'.
        """
        result = await self._get("problemset.problems")
        return result or {"problems": [], "problemStatistics": []}
