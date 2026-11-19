"""The built web app on the address of the API.

`WEB_DIR` is the web folder. It is in the API package, so its location does not change with the
working directory. The Docker image copies the built web app into it. `serve_web` adds one route
that the app matches last. A built file in the web folder comes back as a file. Files under
`assets/` have a content hash in their names, so a browser can keep them for one year. Every
other browser path gets `index.html`, and the web app reads the path itself.

The route does not match a path under `/api`. Thus an unknown API path keeps the 404 of the API,
and an API route that does not accept GET keeps its 405.

When the web folder has no `index.html`, `serve_web` adds no route and the app serves the API only.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from starlette.routing import Match

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.types import Scope

WEB_DIR = Path(__file__).resolve().parent / "web_dist"
INDEX = "index.html"
ASSETS = "assets"
ASSET_CACHE = "public, max-age=31536000, immutable"
INDEX_CACHE = "no-cache"


class _WebRoute(APIRoute):
    """A route that leaves every path under `/api` to the API routes."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        if match is not Match.NONE:
            path = child_scope["path_params"]["path"]
            if path == "api" or path.startswith("api/"):
                return Match.NONE, {}
        return match, child_scope


def serve_web(app: FastAPI) -> None:
    """Serve the built web app in ``WEB_DIR`` on every path that no API route takes.

    Call it after the last router, because the app tries its routes in order.

    When ``WEB_DIR`` has no `index.html`, the app gets no web route.
    """
    root = WEB_DIR.resolve()
    index = root / INDEX
    if not index.is_file():
        return

    def web_page(path: str) -> FileResponse:
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(status_code=404)
        if target.is_file():
            headers: dict[str, str] = {}
            if target.is_relative_to(root / ASSETS):
                headers["Cache-Control"] = ASSET_CACHE
            return FileResponse(target, headers=headers)
        if path == ASSETS or path.startswith(f"{ASSETS}/"):
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": INDEX_CACHE})

    app.router.add_api_route(
        "/{path:path}",
        web_page,
        methods=["GET", "HEAD"],
        include_in_schema=False,
        route_class_override=_WebRoute,
    )


__all__ = ["WEB_DIR", "serve_web"]
