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

# Subset of Ollama models we have verified to expose the OpenAI
# ``tools`` field (i.e. real function-calling). Anything else returns
# HTTP 400 ``"<model> does not support tools"`` and the agent loops
# forever — we surface this as a hard error instead.
TOOL_CAPABLE_OLLAMA_MODELS = (
    "qwen2.5",
    "qwen3",
    "llama3.1",
    "llama3.2",
    "llama3.3",
    "mistral-nemo",
    "mistral-small",
    "command-r",
    "firefunction",
    "hermes3",
    "smollm2",
)


class UnsupportedToolingError(RuntimeError):
    """Raised when the model rejects the ``tools`` field.

    llm-search-kit *requires* tool-calling: the agent emits a
    ``search_catalog`` tool call to talk to the catalog. If the LLM
    can't honour that, we stop early with a clear, actionable message
    rather than retrying forever and returning a useless ``None``.
    """


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
        self._timeout = timeout

    async def aclose(self) -> None:
        # No long-lived state to release: we open a fresh
        # ``httpx.AsyncClient`` per request so the client survives
        # being shared across short-lived event loops (Flask + per-
        # request ``asyncio.new_event_loop``). See the docstring on
        # ``chat_completion`` for the rationale.
        return None

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send one chat-completion request.

        Notes
        -----
        We deliberately open a fresh ``httpx.AsyncClient`` for every
        call instead of caching one on ``self``. The cached variant
        (used historically) crashes with ``RuntimeError: Event loop
        is closed`` when the caller is a sync framework like Flask
        that builds a new event loop per request: the client gets
        bound to the first loop, which is then closed, and the
        underlying anyio transport refuses to be reused on the next
        loop. Per-call construction is ~0.2 ms of overhead and makes
        the client safe in every host (Quart, Flask, FastAPI,
        scripts).
        """
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

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code != 200:
                    body_excerpt = resp.text[:300]
                    logger.error(
                        "[LLM] HTTP %d from %s: %s",
                        resp.status_code, self.base_url, body_excerpt,
                    )
                    if tools and self._looks_like_unsupported_tools(resp):
                        raise UnsupportedToolingError(
                            self._unsupported_tools_message(body_excerpt)
                        )
                    if 500 <= resp.status_code < 600 and attempt < self.max_retries:
                        await asyncio.sleep(_RETRY_BACKOFF_BASE * attempt)
                        continue
                    return None
                result = resp.json()
                self._log_usage(result)
                return result
            except UnsupportedToolingError:
                raise
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

    @staticmethod
    def _looks_like_unsupported_tools(resp: httpx.Response) -> bool:
        """Detect Ollama / llama.cpp / vLLM "no tool support" responses.

        Examples seen in the wild::

            HTTP 400  {"error":{"message":"registry.ollama.ai/library/llama3:latest
                       does not support tools","type":"invalid_request_error"}}
            HTTP 400  {"error":{"message":"this model does not support function calling"}}
            HTTP 422  {"detail":"tools field not supported by this model"}
        """
        if resp.status_code not in (400, 404, 422, 501):
            return False
        body = resp.text.lower()
        needles = (
            "does not support tools",
            "does not support function",
            "tools field not supported",
            "function calling is not supported",
            "tool_choice is not supported",
        )
        return any(n in body for n in needles)

    def _unsupported_tools_message(self, body_excerpt: str) -> str:
        compatible = ", ".join(TOOL_CAPABLE_OLLAMA_MODELS)
        return (
            f"The model {self.model!r} at {self.base_url!r} rejected the "
            "request because it does not support OpenAI-style tool / "
            "function calling, which llm-search-kit requires.\n\n"
            f"Provider response: {body_excerpt}\n\n"
            "Pick a model that DOES support tools. For Ollama (local) the "
            f"verified-good families are: {compatible}.\n"
            "Concretely, set in your .env:\n"
            "  LLM_BASE_URL=http://localhost:11434/v1\n"
            "  LLM_API_KEY=\n"
            "  LLM_MODEL=qwen2.5:1.5b      # small + tool-capable\n"
            "then run:  ollama pull qwen2.5:1.5b\n\n"
            "For hosted OpenAI-compatible providers, any of these work:\n"
            "  OpenAI         gpt-4o-mini, gpt-4o\n"
            "  Groq           llama-3.1-70b-versatile, llama-3.3-70b-versatile\n"
            "  Mistral        mistral-small-latest, mistral-large-latest\n"
            "  OpenRouter     openai/gpt-4o-mini, anthropic/claude-3.5-sonnet"
        )

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
