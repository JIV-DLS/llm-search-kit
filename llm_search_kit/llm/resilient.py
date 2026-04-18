"""Decorator that adds automatic fallback between LLM providers.

Adapted from ``rede/backend/chatbot-service/agent/llm_client.py::ResilientLLMClient``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import BaseLLMClient

logger = logging.getLogger(__name__)


class ResilientLLMClient(BaseLLMClient):
    """Try ``primary`` first; on ``None`` (network error, 5xx, timeout) try ``fallback``."""

    def __init__(self, primary: BaseLLMClient, fallback: BaseLLMClient):
        self._primary = primary
        self._fallback = fallback

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        result = await self._primary.chat_completion(
            messages, tools, temperature, max_tokens, response_format,
        )
        if result is not None:
            return result

        logger.warning(
            "[LLM-FALLBACK] Primary (%s) failed, falling back to %s",
            type(self._primary).__name__,
            type(self._fallback).__name__,
        )
        return await self._fallback.chat_completion(
            messages, tools, temperature, max_tokens, response_format,
        )

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._fallback.aclose()
