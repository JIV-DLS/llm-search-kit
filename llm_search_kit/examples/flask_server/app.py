"""Reference Flask app exposing ``POST /chat`` powered by llm-search-kit.

Designed to be **copy-pasted into your own Flask project** with minimal
edits. The only things you typically change are:

  * ``build_catalog()`` -- swap the in-memory demo catalog for your real
    backend (e.g. ``ElasticsearchCatalog`` from
    ``llm_search_kit.examples.elasticsearch_catalog``).
  * ``build_schema()`` -- declare the filters the LLM is allowed to extract.
  * ``SYSTEM_PROMPT`` -- give the assistant your brand's voice and rules.

The handler uses ``asyncio.new_event_loop`` per request to bridge sync
Flask with the async kit. That is fine for prototyping. For production
prefer Quart (drop-in async Flask) so you can ``await engine.process(...)``
directly -- there is a Quart skeleton at the bottom of this file.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

try:
    from flask import Flask, Response, jsonify, request
except ImportError as exc:  # pragma: no cover -- the CLI prints a friendlier error.
    raise ImportError(
        "The flask_server example needs Flask. Install it with: pip install flask"
    ) from exc

from llm_search_kit import AgentEngine, BaseLLMClient, SearchCatalogSkill
from llm_search_kit.config import build_default_llm_client, llm_api_key
from llm_search_kit.search.backend import CatalogBackend
from llm_search_kit.search.schema import SearchSchema

from ..amazon_products.catalog import InMemoryAmazonCatalog
from ..amazon_products.schema import build_schema as build_amazon_schema

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Shoply, a friendly shopping assistant.

Rules:
- ALWAYS call the `search_catalog` tool when the user is looking for a product.
- Extract structured filters (category, brand, color, size, max_price, ...)
  from their message and put them in the tool arguments. The remaining
  free-text words go into `query`.
- After the tool returns, recommend 1-3 items in a short, friendly paragraph,
  mentioning price + 1 selling point each.
- If the tool relaxed the filters (`relaxation_level > 0`), briefly tell
  the user you broadened the search.
- If `total == 0`, apologise and ask one clarifying question.
- Never expose internal field names like `_id` or `relaxation_level`.
"""


# --------------------------------------------------------------------- factory


def build_catalog() -> CatalogBackend:
    """Override this in your own app to return your real backend.

    Example with Elasticsearch:

        from elasticsearch import AsyncElasticsearch
        from llm_search_kit.examples.elasticsearch_catalog import ElasticsearchCatalog

        es = AsyncElasticsearch(os.environ["ES_URL"])
        return ElasticsearchCatalog(es, index="products")
    """
    return InMemoryAmazonCatalog()


def build_schema() -> SearchSchema:
    """Override this in your own app to describe your search surface."""
    return build_amazon_schema()


def create_app(
    *,
    catalog: Optional[CatalogBackend] = None,
    schema: Optional[SearchSchema] = None,
    llm_client: Optional[BaseLLMClient] = None,
    system_prompt: str = SYSTEM_PROMPT,
    history_size: int = 12,
) -> Flask:
    """Build and return a configured Flask app.

    Parameters
    ----------
    catalog, schema:
        Allow tests / production wiring to inject custom implementations
        without touching the module-level defaults.
    llm_client:
        If provided, use this LLM client (typically a test double). If not
        provided, build one from environment variables via
        :func:`llm_search_kit.config.build_default_llm_client`, in which
        case ``LLM_API_KEY`` MUST be set.
    history_size:
        How many ``(user, assistant)`` message pairs to remember per session.
    """
    app = Flask(__name__)

    catalog = catalog or build_catalog()
    schema  = schema  or build_schema()

    if llm_client is None:
        if not llm_api_key():
            raise RuntimeError(
                "LLM_API_KEY is not set. Copy .env.example to .env and fill it in, "
                "or set the environment variable before starting the server."
            )
        llm_client = build_default_llm_client()

    skill  = SearchCatalogSkill(schema=schema, backend=catalog)
    engine = AgentEngine(llm_client=llm_client, system_prompt=system_prompt)
    engine.register_skill(skill)

    # In-memory session store. **Replace with Redis** for multi-process deployments.
    sessions: Dict[str, Deque[Dict[str, str]]] = defaultdict(
        lambda: deque(maxlen=history_size * 2)
    )

    app.config["LSK_ENGINE"]   = engine
    app.config["LSK_SESSIONS"] = sessions

    # ----------------------------------------------------------- routes
    @app.get("/health")
    def health() -> Response:
        return jsonify(
            status="ok",
            skills=engine.available_skills,
        )

    @app.post("/chat")
    def chat() -> Response:
        payload = request.get_json(silent=True) or {}
        message = (payload.get("message") or "").strip()
        session_id = payload.get("session_id") or "anon"
        user_id = payload.get("user_id")

        if not message:
            return jsonify(error="`message` is required"), 400

        history = list(sessions[session_id])
        context = {"user_id": user_id} if user_id else None

        try:
            result = _run_async(engine.process(
                message,
                conversation_history=history,
                context=context,
            ))
        except Exception:
            logger.exception("Agent processing failed for session %s", session_id)
            return jsonify(
                error="agent_failure",
                message="Something went wrong on our side. Please try again.",
            ), 500

        sessions[session_id].append({"role": "user",      "content": message})
        sessions[session_id].append({"role": "assistant", "content": result.get("reply", "")})

        data = result.get("data") or {}
        return jsonify({
            "reply":    result.get("reply", ""),
            "products": data.get("items", []),
            "meta": {
                "total":            data.get("total", 0),
                "relaxation_level": data.get("relaxation_level", 0),
                "filters_used":     data.get("filters_used", {}),
                "tool_calls":       len(result.get("tool_calls", [])),
            },
        })

    @app.post("/sessions/<session_id>/reset")
    def reset_session(session_id: str) -> Response:
        sessions.pop(session_id, None)
        return jsonify(status="ok")

    return app


# --------------------------------------------------------------------- helpers


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync Flask handler.

    Creates a fresh event loop per request. Acceptable for prototypes; for
    production switch to Quart (see the bottom of this file).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --------------------------------------------------------------------- main


def main() -> None:
    """``python -m llm_search_kit.examples.flask_server.app`` -- dev server."""
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    create_app().run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Production note: Quart skeleton
# ---------------------------------------------------------------------------
# When you outgrow the per-request event loop, switch to Quart (Flask's
# async sibling, almost identical API):
#
#     pip install quart
#
#     from quart import Quart, jsonify, request
#     app = Quart(__name__)
#
#     @app.post("/chat")
#     async def chat():
#         payload = await request.get_json()
#         result = await engine.process(payload["message"], ...)
#         return jsonify(...)
#
#     # uvicorn my_app:app --host 0.0.0.0 --port 8080
#
# Everything else (engine, skill, catalog, sessions) stays exactly the same.
