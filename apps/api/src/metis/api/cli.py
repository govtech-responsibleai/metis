"""The `metis-api` process entry point.

Starts the ASGI server on the composed app. `--project-dir` names the project folder of the
store. Without it, the API finds the project folder from the working directory, with the same
rule as `metis engine simulate`. Host and port come from the environment so a container can set
them without a code change; both have local-friendly defaults.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _existing_folder(value: str) -> Path:
    folder = Path(value).expanduser().resolve()
    if not folder.is_dir():
        raise argparse.ArgumentTypeError(f"'{folder}' is not an existing folder.")
    return folder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metis-api", description="Run the METIS API under Uvicorn."
    )
    parser.add_argument(
        "--project-dir",
        type=_existing_folder,
        default=None,
        metavar="PATH",
        help=(
            "Existing project folder that holds experiments/. The store and the Experiments go "
            "under it. Default: the nearest folder at or above the working directory that has a "
            "pyproject.toml, else the working directory."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the API under Uvicorn."""
    import uvicorn

    from metis.api.main import create_app
    from metis.api.settings import DEFAULT_HOST
    from metis.core.model_settings import load_env

    arguments = _parser().parse_args(argv)
    load_env()
    host = os.environ.get("HOST", DEFAULT_HOST)
    port = int(os.environ.get("PORT", "8000"))
    # Uvicorn gets the app object, so the app keeps the project folder of this command. An
    # import string would make a new app without it. One process with no reload accepts an object.
    app = create_app(project_dir=arguments.project_dir)
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = ["main"]
