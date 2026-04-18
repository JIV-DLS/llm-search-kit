"""CLI entry point for the Flask example.

Usage::

    pip install flask
    cp .env.example .env  # set LLM_API_KEY etc.
    python -m llm_search_kit.examples.flask_server.run --port 5000

Then::

    curl -s http://127.0.0.1:5000/chat \
        -H 'Content-Type: application/json' \
        -d '{"message": "find me red Nike shoes under $80", "session_id": "demo"}' | jq
"""
from __future__ import annotations

import argparse
import logging

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="llm-search-kit Flask demo server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true",
                        help="Enable Flask debug mode (auto-reload + tracebacks).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress INFO-level logs from the kit.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO)

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
