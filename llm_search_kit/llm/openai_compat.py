"""OpenAI-compatible chat-completions client.

Works against any provider that exposes the OpenAI ``/chat/completions``
contract: OpenAI, Groq, OpenRouter, Together, vLLM, llama.cpp, Ollama
(``/v1`` mode), LiteLLM gateway, etc.

Adapted from ``rede/backend/chatbot-service/agent/llm_client.py::GatewayLLMClient``,
stripped of metering / authorization metadata / Ollama-specific branches.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseLLMClient

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120.0
_DEFAULT_MAX_RETRIES = 2
_RETRY_BACKOFF_BASE = 0.5  # seconds


class OpenAILLMClient(BaseLLMClient):
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max(1, max_retries)
        self._extra_headers = dict(extra_headers or {})
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format

        headers = {"Content-Type": "application/json", **self._extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        client = self._get_client()

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.error(
                        "[LLM] HTTP %d from %s: %s",
                        resp.status_code, self.base_url, resp.text[:300],
                    )
                    if 500 <= resp.status_code < 600 and attempt < self.max_retries:
                        await asyncio.sleep(_RETRY_BACKOFF_BASE * attempt)
                        continue
                    return None
                result = resp.json()
                self._log_usage(result)
                return result
            except httpx.TimeoutException:
                logger.warning("[LLM] Timeout (attempt %d/%d)", attempt, self.max_retries)
            except httpx.RequestError as exc:
                logger.error("[LLM] Network error: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("[LLM] Unexpected error: %s", exc)
            if attempt >= self.max_retries:
                return None
            await asyncio.sleep(_RETRY_BACKOFF_BASE * attempt)
        return None

    def _log_usage(self, response: Dict[str, Any]) -> None:
        usage = response.get("usage") or {}
        if not usage:
            return
        logger.info(
            "[LLM-USAGE] model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d",
            response.get("model", self.model),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0),
        )
