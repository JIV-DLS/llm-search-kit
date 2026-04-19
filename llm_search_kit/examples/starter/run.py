"""``python -m llm_search_kit.examples.starter.run`` — boot the demo.

This script is the dev launcher for the starter template. It is *not*
something you copy into your own project — your project will use
``gunicorn``, ``uvicorn``, or your own runner. It exists here purely so
you can see the starter run in 10 seconds.
"""
from __future__ import annotations

import argparse
import logging
import os

from llm_search_kit.config import assert_llm_credentials

from .service import make_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Starter template demo server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    assert_llm_credentials(
        hint="For Ollama: LLM_BASE_URL=http://localhost:11434/v1 and LLM_API_KEY can be empty.",
    )

    app = make_app()
    skills = app.config["LSK_ENGINE"].available_skills
    logging.info("Starter app ready on http://%s:%d (skills: %s)", args.host, args.port, skills)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
