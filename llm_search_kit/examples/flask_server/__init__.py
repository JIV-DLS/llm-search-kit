"""Minimal Flask server exposing the agent over HTTP.

See ``app.py`` for the application factory and ``run.py`` for a CLI
entry point. Install the optional dependency::

    pip install flask
"""
from .app import create_app

__all__ = ["create_app"]
