"""FastAPI runtime surface for OpsMind."""

from typing import Any


def __getattr__(name: str) -> Any:
    """Load the application factory without importing it for submodules."""

    if name == "create_app":
        from opsmind.api.app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["create_app"]
