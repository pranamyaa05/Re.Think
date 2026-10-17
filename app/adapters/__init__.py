"""Adapters module."""
from app.adapters.codeforces import CodeforcesAdapter, CodeforcesAPIError
from app.adapters.leetcode import LeetCodeAdapter, LeetCodeAPIError

__all__ = ["CodeforcesAdapter", "CodeforcesAPIError", "LeetCodeAdapter", "LeetCodeAPIError"]
