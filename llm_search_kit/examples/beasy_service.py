"""Ready-to-run Flask chat service backed by the Beasyapp Spring backend.

This is the single entry point referenced from ``GETTING_STARTED.md``. It
combines the generic :func:`llm_search_kit.examples.flask_server.app.create_app`
factory with the :class:`BeasyappCatalog` adapter so the only thing the
operator needs to do is::

    cp .env.example .env  # set LLM_API_KEY etc.
    python -m llm_search_kit.examples.beasy_service \
        --beasy-url https://actinolitic-glancingly-saturnina.ngrok-free.dev

…and a usable ``POST /chat`` endpoint pops up on port 5000.

Endpoints exposed (inherited from ``flask_server``):

  * ``GET  /health`` — liveness + which skills are registered.
  * ``POST /chat``    — ``{message, session_id, user_id?}`` ->
    ``{reply, products, meta}``.
  * ``POST /sessions/<session_id>/reset`` — wipe a session's history.

For a different backend, copy this file and swap ``BeasyappCatalog`` for
your own ``CatalogBackend``.
"""
from __future__ import annotations

import argparse
import logging
import os
from typing import Optional

from llm_search_kit import BaseLLMClient
from llm_search_kit.examples.beasyapp_backend.catalog import BeasyappCatalog
from llm_search_kit.examples.beasyapp_backend.categories_skill import CategoriesSkill
from llm_search_kit.examples.beasyapp_backend.schema import build_schema
from llm_search_kit.examples.flask_server.app import create_app as create_flask_app

logger = logging.getLogger(__name__)

DEFAULT_BEASY_URL = "https://actinolitic-glancingly-saturnina.ngrok-free.dev"
DEFAULT_SOUL_PATH = os.path.join(
    os.path.dirname(__file__), "beasyapp_backend", "soul.md",
)


def _load_soul(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        logger.warning("Could not read soul prompt at %s; falling back to a stub.", path)
        return "You are Beasy, a friendly Beasyapp shopping assistant."


def make_app(
    beasy_url: str = DEFAULT_BEASY_URL,
    *,
    soul_path: str = DEFAULT_SOUL_PATH,
    auth_header: Optional[str] = None,
    llm_client: Optional[BaseLLMClient] = None,
    enable_categories_skill: bool = True,
):
    """Build a Flask app wired to the Beasyapp backend.

    Parameters
    ----------
    beasy_url:
        Base URL of the Beasyapp Spring backend.
    soul_path:
        Path to the system-prompt markdown file (the assistant's "soul").
    auth_header:
        If set, forwarded as the ``Authorization`` header on every backend
        call. Use this once your search endpoint is no longer publicly open.
    llm_client:
        Override the default OpenAI-compatible LLM client. Useful for tests
        (inject a deterministic stub) and for production wiring (inject a
        ``ResilientLLMClient`` with a fallback provider). When omitted the
        kit reads ``LLM_API_KEY`` / ``LLM_BASE_URL`` / ``LLM_MODEL`` from
        the environment via :func:`llm_search_kit.config.build_default_llm_client`.
    enable_categories_skill:
        If True (default), also register the
        :class:`CategoriesSkill` so the LLM can answer questions like
        "what categories do you sell?" by hitting
        ``GET /api/v1/categories`` instead of trying to abuse the
        ``search_catalog`` tool. Set False if you do not expose
        that endpoint yet — the agent will simply not have that
        capability and will fall back to its general knowledge.

        This flag is the canonical example of "adding a tool requires
        no changes to ``soul.md``": the LLM discovers the new tool
        purely from its name + description + JSON schema.
    """
    headers = {"Authorization": auth_header} if auth_header else None
    catalog = BeasyappCatalog(base_url=beasy_url, headers=headers)
    schema  = build_schema()

    extra_skills = []
    if enable_categories_skill:
        extra_skills.append(CategoriesSkill(base_url=beasy_url, headers=headers))

    app = create_flask_app(
        catalog=catalog,
        schema=schema,
        llm_client=llm_client,
        system_prompt=_load_soul(soul_path),
        extra_skills=extra_skills,
    )
    app.config["BEASY_BACKEND_URL"] = beasy_url
    return app


# Module-level WSGI app, so ``gunicorn llm_search_kit.examples.beasy_service:app``
# Just Works(tm). Built lazily on first import to avoid pulling in Flask /
# building the LLM client when this module is merely imported by tests.
def _lazy_app():
    return make_app(
        beasy_url=os.environ.get("BEASY_BASE_URL", DEFAULT_BEASY_URL),
        auth_header=os.environ.get("BEASY_AUTH_HEADER"),
    )


def __getattr__(name):  # PEP 562
    if name == "app":
        global app
        app = _lazy_app()
        return app
    raise AttributeError(name)


def main() -> None:
    p = argparse.ArgumentParser(description="Beasyapp chat service (Flask).")
    p.add_argument(
        "--beasy-url",
        default=os.environ.get("BEASY_BASE_URL", DEFAULT_BEASY_URL),
        help="URL of the Beasyapp Spring backend (default: %(default)s).",
    )
    p.add_argument(
        "--auth-header",
        default=os.environ.get("BEASY_AUTH_HEADER"),
        help='Value for the Authorization header sent to the backend, e.g. "Bearer xxx".',
    )
    p.add_argument(
        "--soul",
        default=DEFAULT_SOUL_PATH,
        help="Path to the system-prompt markdown file (default: bundled).",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true",
                   help="Enable Flask debug mode (auto-reload + tracebacks).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress INFO-level logs.")
    p.add_argument(
        "--no-categories-skill", action="store_true",
        help=(
            "Do NOT register the CategoriesSkill (default: it IS registered). "
            "Use this if your Spring backend doesn't expose "
            "GET /api/v1/categories yet."
        ),
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    application = make_app(
        beasy_url=args.beasy_url,
        soul_path=args.soul,
        auth_header=args.auth_header,
        enable_categories_skill=not args.no_categories_skill,
    )

    logger.info("Beasy chat service ready on http://%s:%d", args.host, args.port)
    logger.info("Backend:  %s", args.beasy_url)
    logger.info("Skills:   %s", application.config["LSK_ENGINE"].available_skills)
    application.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
