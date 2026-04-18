"""Tiny env-loader so examples can be one-liner runnable.

Reads ``.env`` (if present) using python-dotenv, then exposes typed accessors.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv()
except ImportError:  # pragma: no cover - dotenv is a hard dep, but be safe
    pass


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def llm_base_url() -> str:
    return _env("LLM_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1"


def llm_api_key() -> str:
    key = _env("LLM_API_KEY", "")
    return key or ""


def llm_model() -> str:
    return _env("LLM_MODEL", "gpt-4o-mini") or "gpt-4o-mini"


def llm_fallback_base_url() -> Optional[str]:
    return _env("LLM_FALLBACK_BASE_URL")


def llm_fallback_api_key() -> Optional[str]:
    return _env("LLM_FALLBACK_API_KEY")


def llm_fallback_model() -> Optional[str]:
    return _env("LLM_FALLBACK_MODEL")


def has_fallback() -> bool:
    return bool(llm_fallback_base_url() and llm_fallback_model())


def build_default_llm_client():
    """Build an ``OpenAILLMClient`` (wrapped in ``ResilientLLMClient`` if a
    fallback provider is configured) using ``.env`` values.

    Lazily imported to avoid forcing httpx onto callers that build their own.
    """
    from .llm import OpenAILLMClient, ResilientLLMClient

    primary = OpenAILLMClient(
        base_url=llm_base_url(),
        api_key=llm_api_key(),
        model=llm_model(),
    )
    if not has_fallback():
        return primary
    fallback = OpenAILLMClient(
        base_url=llm_fallback_base_url() or "",
        api_key=llm_fallback_api_key() or "",
        model=llm_fallback_model() or "",
    )
    return ResilientLLMClient(primary=primary, fallback=fallback)
