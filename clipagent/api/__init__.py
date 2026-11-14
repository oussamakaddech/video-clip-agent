"""API HTTP de clipagent."""

from __future__ import annotations

__all__ = ["create_app"]


def create_app(*args, **kwargs):
    """Import différé : FastAPI n'est requis que si l'API est utilisée."""
    from .server import create_app as _create_app

    return _create_app(*args, **kwargs)
