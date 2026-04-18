"""Abstract base for LLM clients (Strategy pattern).

Any concrete client must implement ``chat_completion`` returning an
OpenAI-compatible response dict (``{"choices": [{"message": {...}}], ...}``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseLLMClient(ABC):
    """Interface for LLM clients."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run a chat completion. Returns OpenAI-shaped dict or None on failure."""
        ...

    async def simple_completion(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
    ) -> Optional[str]:
        """Convenience: send a single user message, return assistant text."""
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        result = await self.chat_completion(messages, temperature=temperature)
        if not result:
            return None
        choices = result.get("choices", [])
        if not choices:
            return None
        return choices[0].get("message", {}).get("content", "")

    async def aclose(self) -> None:
        """Release any held resources (e.g. http client). Default is a no-op."""
        return None
