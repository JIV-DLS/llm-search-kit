"""Wire your skills into a Flask ``POST /chat`` service. Copy + adapt.

Three things you customise per project (everything else stays as-is):

* **system prompt** — your assistant's voice, rules, and constraints.
* **skills module** — the dotted path of YOUR skills file (here we use
  the sibling ``my_skills`` for the demo).
* **search backend** — *if* you want the built-in ``search_catalog``
  tool. Set ``enable_default_search_skill=False`` to turn it off when
  your assistant is not a product-search bot.

This file is ~30 lines because all the heavy lifting lives in
``llm_search_kit.examples.flask_server.app.create_app``. Treat that as
a black box: you only ever pass kwargs.
"""
from __future__ import annotations

import logging
from typing import Optional

from flask import Flask

from llm_search_kit import BaseLLMClient
from llm_search_kit.examples.flask_server.app import create_app as create_flask_app

from . import my_skills

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a friendly assistant powered by llm-search-kit.

You can:
- Convert currencies via the `convert_currency` tool.
- Greet the user via the `greet_user` tool (uses their preferred language
  from `ctx`).

When the user asks something a tool can answer, ALWAYS call the tool
instead of guessing. After it returns, summarise the result in one
short sentence."""


def make_app(*, llm_client: Optional[BaseLLMClient] = None) -> Flask:
    """Build the Flask app exposing ``POST /chat`` for this starter project.

    Parameters
    ----------
    llm_client:
        Inject a fake LLM client in tests; leave ``None`` in production
        to let the kit build one from ``LLM_API_KEY`` / ``LLM_BASE_URL``
        / ``LLM_MODEL`` environment variables.
    """
    return create_flask_app(
        system_prompt=SYSTEM_PROMPT,
        skills_module=my_skills,
        enable_default_search_skill=False,
        llm_client=llm_client,
    )
