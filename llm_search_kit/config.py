"""Tiny env-loader so examples can be one-liner runnable.

Reads ``.env`` (if present) using python-dotenv, then exposes typed accessors.
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

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


# Hostnames whose servers serve OpenAI-compatible endpoints **without**
# requiring an API key. Anything matching here is treated as "no key
# needed" so the CLI / examples don't refuse to start.
_KEYLESS_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "host.docker.internal",
    "ollama",  # common docker-compose service name
    "vllm",
}


def llm_provider_requires_key(base_url: Optional[str] = None) -> bool:
    """Return True if the configured LLM provider needs an API key.

    Local OpenAI-compatible runtimes (Ollama, llama.cpp ``--api``,
    self-hosted vLLM, etc.) accept calls without authentication, so
    the CLI shouldn't refuse to start when ``LLM_API_KEY`` is empty
    in those setups. We detect them by inspecting ``LLM_BASE_URL``:
    anything pointing to localhost, ``127.0.0.1`` or a hostname in
    :data:`_KEYLESS_HOSTS`, or any URL whose hostname ends with
    ``.local`` or ``.lan``, is treated as keyless.
    """
    url = base_url if base_url is not None else llm_base_url()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return True
    if host in _KEYLESS_HOSTS:
        return False
    if host.endswith(".local") or host.endswith(".lan"):
        return False
    return True


def assert_llm_credentials(*, hint: str = "") -> None:
    """Fail fast with a clear message when the LLM cannot be called.

    Raises :class:`SystemExit` with a single, copy-pasteable message
    rather than letting the underlying HTTP client bubble up a less
    actionable ``401`` later. Safe to call at process start of any
    example / script.

    Skips the check when the configured provider is local (Ollama,
    vLLM, llama.cpp, etc.) since those don't require a key.
    """
    if not llm_provider_requires_key():
        return
    if llm_api_key():
        return
    msg = (
        "LLM_API_KEY is not set and LLM_BASE_URL points to a remote "
        f"provider ({llm_base_url()!r}) that needs an API key.\n"
        "Either:\n"
        "  - copy .env.example to .env and fill in LLM_API_KEY, or\n"
        "  - export LLM_API_KEY=<your key> in this shell, or\n"
        "  - point LLM_BASE_URL at a local Ollama / vLLM / llama.cpp\n"
        "    server (e.g. http://localhost:11434/v1 for Ollama) — those\n"
        "    don't need a key."
    )
    if hint:
        msg = f"{msg}\n\n{hint}"
    raise SystemExit(msg)


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
