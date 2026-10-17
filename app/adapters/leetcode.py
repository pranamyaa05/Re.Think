"""
Async client adapter for the LeetCode GraphQL API.

Key design details:
- Respects rate limits via in-memory token/interval throttling (default 1.0 req/s).
- All requests are strictly outside database transactions.
- Handles public endpoints and cookie-authenticated endpoints (via LEETCODE_SESSION).
- Normalizes verdicts at adapter layer:
    "Accepted" -> "OK"
    "Wrong Answer" -> "WRONG_ANSWER"
    "Time Limit Exceeded" -> "TIME_LIMIT_EXCEEDED"
    "Memory Limit Exceeded" -> "MEMORY_LIMIT_EXCEEDED"
    "Runtime Error" -> "RUNTIME_ERROR"
    "Compile Error" -> "COMPILATION_ERROR"
- Robust retry logic with exponential backoff on transient errors.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LeetCodeAPIError(Exception):
    """Raised when the LeetCode GraphQL API returns an error or non-200 status."""
    pass


LEETCODE_VERDICT_MAP = {
    "Accepted": "OK",
    "Wrong Answer": "WRONG_ANSWER",
    "Time Limit Exceeded": "TIME_LIMIT_EXCEEDED",
    "Memory Limit Exceeded": "MEMORY_LIMIT_EXCEEDED",
    "Runtime Error": "RUNTIME_ERROR",
    "Compile Error": "COMPILATION_ERROR",
    "Output Limit Exceeded": "OUTPUT_LIMIT_EXCEEDED",
}


def normalize_leetcode_verdict(raw_verdict: Optional[str]) -> str:
    """Normalizes LeetCode verdict string to standard platform verdict."""
    if not raw_verdict:
        return "UNKNOWN"
    return LEETCODE_VERDICT_MAP.get(
        raw_verdict,
        raw_verdict.strip().upper().replace(" ", "_")
    )


class LeetCodeAdapter:
    def __init__(
        self,
        base_url: Optional[str] = None,
        requests_per_second: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.leetcode_api_base_url).rstrip("/")
        rps = requests_per_second or getattr(settings, "leetcode_requests_per_second", 1.0)
        self.min_interval = 1.0 / max(0.1, rps)
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

    async def _post(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends an authenticated or unauthenticated GraphQL POST request to LeetCode."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://leetcode.com",
            "Origin": "https://leetcode.com",
        }

        if auth_token and auth_token.strip():
            token_clean = auth_token.strip()
            if "LEETCODE_SESSION=" in token_clean:
                headers["Cookie"] = token_clean
            else:
                headers["Cookie"] = f"LEETCODE_SESSION={token_clean}"

        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        max_retries = 3
        backoff = 2.0

        for attempt in range(1, max_retries + 1):
            await self._throttle()
            async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
                try:
                    response = await client.post(self.base_url, json=payload)
                except httpx.HTTPError as exc:
                    if attempt == max_retries:
                        raise LeetCodeAPIError(f"HTTP request to LeetCode failed: {exc}") from exc
                    await asyncio.sleep(backoff * attempt)
                    continue

                if response.status_code in (429, 502, 503, 504):
                    if attempt == max_retries:
                        raise LeetCodeAPIError(
                            f"LeetCode returned HTTP {response.status_code}: {response.text[:300]}"
                        )
                    await asyncio.sleep(backoff * attempt)
                    continue

                if response.status_code != 200:
                    raise LeetCodeAPIError(
                        f"LeetCode returned HTTP {response.status_code}: {response.text[:300]}"
                    )

                try:
                    data = response.json()
                except ValueError as exc:
                    raise LeetCodeAPIError(f"Invalid JSON returned by LeetCode API: {exc}") from exc

                if isinstance(data, dict) and data.get("errors") and not data.get("data"):
                    err_msg = "; ".join(e.get("message", "Unknown error") for e in data["errors"])
                    raise LeetCodeAPIError(f"LeetCode GraphQL error: {err_msg}")

                return data.get("data") or {}

        raise LeetCodeAPIError("Unexpected retry termination in LeetCode client.")

    async def get_authenticated_user(
        self, auth_token: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch authenticated user identity (username, realName, isSignedIn) from session cookie."""
        query = """
        query globalData {
          userStatus {
            userId
            isSignedIn
            username
            realName
          }
        }
        """
        try:
            data = await self._post(query, auth_token=auth_token)
            status = data.get("userStatus")
            if status and status.get("isSignedIn"):
                return status
            return None
        except Exception as e:
            logger.warning(f"Could not verify authenticated user from cookie: {e}")
            return None

    async def get_user_profile(
        self, username: str, auth_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch public profile and submission statistics for a LeetCode user."""
        query = """
        query getUserProfile($username: String!) {
          matchedUser(username: $username) {
            username
            profile {
              realName
              ranking
              userAvatar
            }
            submitStats: submitStatsGlobal {
              acSubmissionNum {
                difficulty
                count
                submissions
              }
            }
          }
        }
        """
        data = await self._post(query, {"username": username}, auth_token=auth_token)
        matched = data.get("matchedUser")
        if not matched:
            raise LeetCodeAPIError(f"LeetCode user '{username}' not found.")
        return matched

    async def get_user_tag_problem_counts(
        self, username: str, auth_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch tag problem counts (fundamental, intermediate, advanced) for a user."""
        query = """
        query skillStats($username: String!) {
          matchedUser(username: $username) {
            tagProblemCounts {
              advanced {
                tagName
                tagSlug
                problemsSolved
              }
              intermediate {
                tagName
                tagSlug
                problemsSolved
              }
              fundamental {
                tagName
                tagSlug
                problemsSolved
              }
            }
          }
        }
        """
        data = await self._post(query, {"username": username}, auth_token=auth_token)
        matched = data.get("matchedUser")
        return (matched.get("tagProblemCounts") if matched else {}) or {}

    async def get_user_contest_ranking(
        self, username: str, auth_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch contest ranking and full contest history for a user."""
        query = """
        query userContestRankingInfo($username: String!) {
          userContestRanking(username: $username) {
            attendedContestsCount
            rating
            globalRanking
            totalParticipants
            topPercentage
          }
          userContestRankingHistory(username: $username) {
            attended
            rating
            ranking
            trendDirection
            problemsSolved
            totalProblems
            finishTimeInSeconds
            contest {
              title
              startTime
            }
          }
        }
        """
        data = await self._post(query, {"username": username}, auth_token=auth_token)
        return {
            "ranking": data.get("userContestRanking"),
            "history": data.get("userContestRankingHistory") or [],
        }

    async def get_recent_submissions(
        self, username: str, limit: int = 20, auth_token: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent submissions for user with normalized verdicts.
        Combines recentSubmissionList (all recent attempts with verdicts/langs)
        and recentAcSubmissionList (recent accepted solves) deduplicated by ID.
        Requires LEETCODE_SESSION cookie (returns empty list without auth).
        """
        query_all = """
        query recentSubmissions($username: String!, $limit: Int!) {
          recentSubmissionList(username: $username, limit: $limit) {
            id
            title
            titleSlug
            timestamp
            statusDisplay
            lang
          }
        }
        """
        data = await self._post(query_all, {"username": username, "limit": limit}, auth_token=auth_token)
        raw_list = list(data.get("recentSubmissionList") or [])
        seen_ids = {str(s.get("id")) for s in raw_list if s.get("id")}

        # Query recent AC submissions and merge any solved problems not in the general recent list
        query_ac = """
        query recentAcSubmissions($username: String!, $limit: Int!) {
          recentAcSubmissionList(username: $username, limit: $limit) {
            id
            title
            titleSlug
            timestamp
          }
        }
        """
        try:
            ac_data = await self._post(query_ac, {"username": username, "limit": limit}, auth_token=auth_token)
            raw_ac = ac_data.get("recentAcSubmissionList") or []
            for item in raw_ac:
                item_id = str(item.get("id"))
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    raw_list.append({
                        "id": item["id"],
                        "title": item["title"],
                        "titleSlug": item["titleSlug"],
                        "timestamp": item["timestamp"],
                        "statusDisplay": "Accepted",
                        "lang": None,
                    })
        except Exception as e:
            logger.warning(f"Could not fetch recentAcSubmissionList: {e}")

        normalized_submissions = []
        for s in raw_list:
            normalized_submissions.append({
                "id": str(s.get("id")),
                "title": s.get("title"),
                "titleSlug": s.get("titleSlug"),
                "timestamp": int(s.get("timestamp", 0)),
                "raw_verdict": s.get("statusDisplay"),
                "verdict": normalize_leetcode_verdict(s.get("statusDisplay")),
                "lang": s.get("lang"),
            })

        return normalized_submissions

    async def get_problemset_problems(
        self, limit: int = 50, skip: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetch list of problems from the LeetCode catalog."""
        query = """
        query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
          problemsetQuestionList: questionList(
            categorySlug: $categorySlug
            limit: $limit
            skip: $skip
            filters: $filters
          ) {
            total: totalNum
            questions: data {
              frontendQuestionId: questionFrontendId
              title
              titleSlug
              difficulty
              topicTags {
                name
                slug
              }
            }
          }
        }
        """
        data = await self._post(
            query,
            {"categorySlug": "", "limit": limit, "skip": skip, "filters": {}},
        )
        qlist = data.get("problemsetQuestionList") or {}
        return qlist.get("questions") or []

    async def get_problem_by_slug(self, title_slug: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed problem information for a single problem by titleSlug."""
        query = """
        query questionData($titleSlug: String!) {
          question(titleSlug: $titleSlug) {
            questionId
            questionFrontendId
            title
            titleSlug
            difficulty
            topicTags {
              name
              slug
            }
          }
        }
        """
        data = await self._post(query, {"titleSlug": title_slug})
        return data.get("question")
