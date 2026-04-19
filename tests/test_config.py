"""Unit tests for ``llm_search_kit.config`` env helpers.

The interesting bit is :func:`assert_llm_credentials`: it must let
*local* OpenAI-compatible servers (Ollama, vLLM, llama.cpp) start
without an API key while still failing fast on remote providers
that need one.
"""
from __future__ import annotations

import importlib

import pytest


def _reload_config(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Reload ``llm_search_kit.config`` with a controlled env."""
    # python-dotenv is invoked at import time and silently overrides
    # whatever we set via monkeypatch, so prevent it from touching
    # the real ``.env`` file in the repo.
    monkeypatch.setenv("DOTENV_PATH", "/nonexistent")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import llm_search_kit.config as cfg
    importlib.reload(cfg)
    return cfg


def test_local_ollama_does_not_require_key(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _reload_config(
        monkeypatch,
        LLM_API_KEY="",
        LLM_BASE_URL="http://localhost:11434/v1",
        LLM_MODEL="qwen2.5:7b",
    )
    assert cfg.llm_provider_requires_key() is False
    cfg.assert_llm_credentials()


@pytest.mark.parametrize("host", [
    "http://127.0.0.1:11434/v1",
    "http://0.0.0.0:8000/v1",
    "http://host.docker.internal:11434/v1",
    "http://ollama:11434/v1",
    "http://my-mac.local:11434/v1",
    "http://server.lan:8000/v1",
])
def test_keyless_hosts(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    cfg = _reload_config(
        monkeypatch,
        LLM_API_KEY="",
        LLM_BASE_URL=host,
        LLM_MODEL="qwen2.5:7b",
    )
    assert cfg.llm_provider_requires_key() is False, host
    cfg.assert_llm_credentials()


def test_remote_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _reload_config(
        monkeypatch,
        LLM_API_KEY="",
        LLM_BASE_URL="https://api.openai.com/v1",
        LLM_MODEL="gpt-4o-mini",
    )
    assert cfg.llm_provider_requires_key() is True
    with pytest.raises(SystemExit) as excinfo:
        cfg.assert_llm_credentials()
    msg = str(excinfo.value)
    assert "LLM_API_KEY is not set" in msg
    assert "Ollama" in msg, "the message should hint the local-server alternative"


def test_remote_with_key_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _reload_config(
        monkeypatch,
        LLM_API_KEY="sk-fake",
        LLM_BASE_URL="https://api.openai.com/v1",
        LLM_MODEL="gpt-4o-mini",
    )
    cfg.assert_llm_credentials()
