"""The built web app on the same address as the API.

The app serves the web folder that `metis.api.web.WEB_DIR` names. Built files come back as files,
every other browser path gets `index.html`, and the API paths keep their own behaviour. Without
a built web app, the app serves the API only. Each test sets `WEB_DIR` to a folder in `tmp_path`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from metis.api.main import create_app
from tests.fixtures.api._shared import scripted_interview_handler

if TYPE_CHECKING:
    from pathlib import Path

    from metis.api.store import Store

INDEX = "<!doctype html><title>METIS</title>"
ASSET = "console.log('metis');"
IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def web_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A built web app: the index page, one hashed asset, and one file at the root."""
    folder = tmp_path / "web"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text(INDEX)
    (folder / "assets" / "app.js").write_text(ASSET)
    (folder / "metis-mark.png").write_bytes(b"png")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr("metis.api.web.WEB_DIR", folder)
    return folder


def _no_web_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    monkeypatch.setattr("metis.api.web.WEB_DIR", folder)


def _client(store: Store) -> TestClient:
    app = create_app(interview_handler=scripted_interview_handler(), store=store)
    return TestClient(app)


@pytest.mark.usefixtures("web_dir")
def test_each_client_route_gets_the_index_page(store: Store) -> None:
    client = _client(store)

    for path in ("/", "/targets/abc/experiments", "/experiments"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.text == INDEX
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
    assert client.head("/targets/abc").status_code == 200


@pytest.mark.usefixtures("web_dir")
def test_built_files_are_served_and_assets_are_cached(store: Store) -> None:
    client = _client(store)

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == ASSET
    assert asset.headers["cache-control"] == IMMUTABLE

    root_file = client.get("/metis-mark.png")
    assert root_file.status_code == 200
    assert root_file.content == b"png"
    assert "immutable" not in root_file.headers.get("cache-control", "")

    assert client.get("/assets/missing.js").status_code == 404


@pytest.mark.usefixtures("web_dir")
def test_api_paths_keep_the_api_behaviour(store: Store) -> None:
    client = _client(store)

    unknown = client.get("/api/v1/nope")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Not Found"}
    assert client.get("/api").status_code == 404
    assert client.get("/api/v1/wizard/interview/start").status_code == 405
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/v1/targets").status_code == 200


@pytest.mark.usefixtures("web_dir")
def test_a_path_outside_the_web_folder_is_refused(store: Store) -> None:
    client = _client(store)

    for path in ("/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "secret" not in response.text


@pytest.mark.usefixtures("web_dir")
def test_the_openapi_document_does_not_change(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = _client(store).get("/openapi.json").json()
    _no_web_app(tmp_path, monkeypatch)
    plain = _client(store).get("/openapi.json").json()

    assert served == plain


def test_without_a_built_web_app_the_app_serves_the_api_only(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_web_app(tmp_path, monkeypatch)
    client = _client(store)

    assert client.get("/").status_code == 404
    assert client.get("/health").json()["status"] == "ok"
