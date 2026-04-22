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


_DEFAULT_GATEWAY = "https://llm.technas.fr/v1"


def llm_base_url() -> str:
    """Base URL for the OpenAI-compatible chat-completions endpoint.

    Defaults to the Technas LLM gateway so any new integration that
    forgets to configure ``LLM_BASE_URL`` ends up on the gateway by
    accident — the safe direction (tracked + billed) instead of
    leaking calls straight to OpenAI.
    """
    return _env("LLM_BASE_URL", _DEFAULT_GATEWAY) or _DEFAULT_GATEWAY


def llm_api_key() -> str:
    key = _env("LLM_API_KEY", "")
    return key or ""


def llm_technas_key() -> str:
    """Payment-issued ``pk_xxx`` caller identity (X-Technas-Key).

    Required when ``LLM_BASE_URL`` points at the Technas gateway so
    the call is attributed to a project on the bypass-tracker
    dashboard. Empty when targeting any other OpenAI-compatible
    provider (the kit is also used for non-Technas demos).
    """
    return _env("LLM_TECHNAS_KEY", "") or ""


def llm_model() -> str:
    # Aligned with the gateway's default routing alias so callers that
    # don't override LLM_MODEL get a sane, multi-provider default
    # rather than a hard-coded OpenAI SKU.
    return _env("LLM_MODEL", "auto-quality") or "auto-quality"


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

# Hostnames that resolve to the Technas LLM gateway. We use this set
# to decide whether to auto-attach the X-Technas-Key header without
# polluting unrelated OpenAI-compat targets.
_TECHNAS_GATEWAY_HOSTS = {
    "llm.technas.fr",
    "llm-gateway-http.technas.svc.cluster.local",
    "llm-gateway-http.production.svc.cluster.local",
}


def is_technas_gateway(base_url: Optional[str] = None) -> bool:
    """True when the configured base URL points at the Technas LLM gateway."""
    url = base_url if base_url is not None else llm_base_url()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in _TECHNAS_GATEWAY_HOSTS


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


def _technas_extra_headers(base_url: str) -> dict:
    """Headers to auto-attach when the target is the Technas gateway.

    We only inject ``X-Technas-Key`` if the configured base URL is
    actually the Technas gateway. For external providers (OpenAI,
    Groq, Mistral…) this would be a leak of internal identifiers, so
    we skip it.
    """
    if not is_technas_gateway(base_url):
        return {}
    technas_key = llm_technas_key()
    if not technas_key:
        return {}
    return {"X-Technas-Key": technas_key}


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
        extra_headers=_technas_extra_headers(llm_base_url()),
    )
    if not has_fallback():
        return primary
    fb_url = llm_fallback_base_url() or ""
    fallback = OpenAILLMClient(
        base_url=fb_url,
        api_key=llm_fallback_api_key() or "",
        model=llm_fallback_model() or "",
        extra_headers=_technas_extra_headers(fb_url),
    )
    return ResilientLLMClient(primary=primary, fallback=fallback)
