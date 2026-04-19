"""Starter template for integrating ``llm-search-kit`` into your own project.

This package is the **canonical "copy this folder" example**. It is
intentionally tiny (3 files, ~150 lines total) and contains zero
project-specific logic. Read order:

1. ``my_skills.py`` — where you declare what the LLM can do (one
   ``@skill``-decorated function per tool).
2. ``service.py``  — 30-line Flask wiring that binds your skills to a
   ``POST /chat`` endpoint. You should not need to touch the kit itself.
3. ``run.py``       — ``python -m llm_search_kit.examples.starter.run``
   to launch the dev server and try it.

When you copy this folder into your own project, you only ever modify
``my_skills.py`` (add tools) and ``service.py`` (system prompt + auth).
Everything else stays in the kit.
"""
