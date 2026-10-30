"""The `metis-api` process entry point.

Starts the ASGI server on the composed app. Host and port come from the environment so a container
can set them without a code change; both have local-friendly defaults.
"""

from __future__ import annotations

import os


def main() -> None:
    """Run the API under Uvicorn."""
    import uvicorn

    from metis.core.model_settings import load_env

    load_env()
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 — a container binds all interfaces
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("metis.api.main:app", host=host, port=port, log_level="info")


__all__ = ["main"]
