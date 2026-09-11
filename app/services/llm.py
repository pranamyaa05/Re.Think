"""
LLM Client service — abstraction supporting Gemini, OpenAI, and Mock providers
with token usage tracking, latency measurement, and DB call logging.
"""

import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import httpx

from app.config import settings
from app.database import async_session_factory
from app.models.llm_call_log import LLMCallLog

logger = logging.getLogger(__name__)


class LLMResponse:
    def __init__(
        self,
        content: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        model: str = "mock",
        latency_ms: int = 0,
    ):
        self.content = content
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.model = model
        self.latency_ms = latency_ms

    def json(self) -> Dict[str, Any]:
        """Convenience method to parse content as JSON."""
        return json.loads(self.content)


class LLMClient:
    def __init__(
        self,
        provider: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        self.provider = provider or settings.llm_provider
        self.gemini_api_key = gemini_api_key or settings.gemini_api_key
        self.openai_api_key = openai_api_key or settings.openai_api_key
        self.custom_mock_handlers: Dict[str, Callable[[str, str], str]] = {}

    def register_mock_handler(self, caller: str, handler: Callable[[str, str], str]):
        """Registers a custom mock generator for a specific caller in unit tests."""
        self.custom_mock_handlers[caller] = handler

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_json: bool = False,
        caller: str = "unknown",
        session_id: Optional[int] = None,
    ) -> LLMResponse:
        """
        Invokes the configured LLM provider, logs the execution into llm_call_log,
        and returns an LLMResponse.
        """
        # 1. Compute prompt hash
        prompt_text = f"{system_prompt}\n---\n{user_prompt}"
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

        start_time = time.perf_counter()

        # 2. Dispatch to provider
        if self.provider == "gemini" and self.gemini_api_key:
            response = await self._call_gemini(
                system_prompt, user_prompt, temperature, response_json
            )
        elif self.provider == "openai" and self.openai_api_key:
            response = await self._call_openai(
                system_prompt, user_prompt, temperature, response_json
            )
        else:
            response = self._call_mock(
                system_prompt, user_prompt, caller, response_json
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        response.latency_ms = latency_ms

        # 3. Asynchronously log call to llm_call_log
        try:
            async with async_session_factory() as session:
                log_entry = LLMCallLog(
                    session_id=session_id,
                    caller=caller,
                    model=response.model,
                    prompt_hash=prompt_hash,
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    latency_ms=latency_ms,
                )
                session.add(log_entry)
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to record LLM call log: {e}")

        return response

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        response_json: bool,
    ) -> LLMResponse:
        model = settings.gemini_model
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.gemini_api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json" if response_json else "text/plain",
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates returned from Gemini API")

        content = candidates[0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        tokens_in = usage.get("promptTokenCount", len(system_prompt + user_prompt) // 4)
        tokens_out = usage.get("candidatesTokenCount", len(content) // 4)

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
        )

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        response_json: bool,
    ) -> LLMResponse:
        model = settings.openai_model
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", len(system_prompt + user_prompt) // 4)
        tokens_out = usage.get("completion_tokens", len(content) // 4)

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
        )

    def _call_mock(
        self,
        system_prompt: str,
        user_prompt: str,
        caller: str,
        response_json: bool,
    ) -> LLMResponse:
        """Realistic deterministic responses for testing."""
        if caller in self.custom_mock_handlers:
            content = self.custom_mock_handlers[caller](system_prompt, user_prompt)
        elif caller == "fsm_evaluator":
            content = json.dumps({
                "understood_current_level": True,
                "extracted_approach": "greedy interval sorting",
                "recommended_next_level": 1,
                "reasoning": "User recognized the sorting property on intervals.",
            })
        elif caller == "judge":
            content = json.dumps({
                "reveals_full_solution": False,
                "contains_executable_code": False,
                "exceeds_level_guidance": False,
                "lacks_problem_context": False,
                "is_vacuous": False,
            })
        elif caller == "editorial_extractor":
            content = json.dumps({
                "approach_summary": "Sort intervals by finish time. Greedily select non-overlapping elements.",
                "key_insight": "Earliest finishing interval leaves maximum remaining time.",
                "techniques": ["greedy", "sortings"],
                "common_pitfalls": ["Sorting by start time instead of end time", "Off-by-one on boundary"],
            })
        elif caller == "hint_generator":
            content = (
                "What is the maximum value of N in the constraints, and how does that "
                "bound the acceptable time complexity for our solution?"
            )
        else:
            content = "{}" if response_json else "Sample response"

        tokens_in = max(10, len(system_prompt + user_prompt) // 4)
        tokens_out = max(5, len(content) // 4)

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model="mock-model",
        )
