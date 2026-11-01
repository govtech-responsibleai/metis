"""The development launcher runs real child processes, so these tests use small Python services."""

from __future__ import annotations

import http.server
import sys
import threading
import time

import metis_dev
import pytest
from metis_dev import LaunchError, Service, launch, run_services


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_labels_each_output_line(capsys):
    code = run_services([Service("one", _python("print('hello'); print('bye')"))])

    out = capsys.readouterr().out
    assert code == 1
    assert "one | hello" in out
    assert "one | bye" in out
    assert "[run] one stopped. Stopping the other servers." in out


def test_a_service_that_stops_stops_the_others(capsys):
    started = time.monotonic()
    code = run_services(
        [
            Service("long", _python("import time; time.sleep(60)")),
            Service("short", _python("import time; time.sleep(0.5)")),
        ]
    )

    # run_services returns only after it has waited for every service to end.
    assert code == 1
    assert time.monotonic() - started < 15
    assert "[run] short stopped." in capsys.readouterr().out


def test_waits_for_ready_url_before_the_next_service(tmp_path):
    marker = tmp_path / "second-started"
    server = http.server.HTTPServer(
        ("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler
    )
    port = server.server_address[1]
    server.server_close()
    first = _python(
        "import http.server, time; time.sleep(1); "
        f"http.server.HTTPServer(('127.0.0.1', {port}), "
        "http.server.SimpleHTTPRequestHandler).serve_forever()"
    )
    second = _python(f"open({str(marker)!r}, 'w').close()")
    started_at: list[float] = []

    def watch() -> None:
        while not marker.exists():
            time.sleep(0.02)
        started_at.append(time.monotonic())

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    begin = time.monotonic()
    run_services(
        [
            Service("first", first, ready_url=f"http://127.0.0.1:{port}/"),
            Service("second", second),
        ]
    )
    watcher.join(timeout=5)

    assert started_at
    assert started_at[0] - begin >= 1


def test_ready_wait_ends_when_the_service_stops(capsys):
    code = run_services(
        [
            Service(
                "api", _python("raise SystemExit(3)"), ready_url="http://127.0.0.1:9/"
            ),
            Service("web", _python("print('must not start')")),
        ]
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "[run] api stopped." in out
    assert "must not start" not in out


def test_missing_prerequisite_prints_one_error(capsys):
    def build() -> list[Service]:
        raise LaunchError("`npm` is not on PATH. Install Node.js, which includes npm.")

    assert launch(build) == 1
    assert "`npm` is not on PATH" in capsys.readouterr().out


@pytest.fixture
def repo_with_web_deps(tmp_path, monkeypatch):
    (tmp_path / "apps" / "web" / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(metis_dev, "REPO_ROOT", tmp_path)


def test_web_services_need_npm(monkeypatch):
    monkeypatch.setattr(metis_dev.shutil, "which", lambda name: None)

    with pytest.raises(LaunchError, match="`npm` is not on PATH"):
        metis_dev.web_services()


def test_web_services_need_the_web_dependencies(monkeypatch, tmp_path):
    monkeypatch.setattr(metis_dev.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(metis_dev, "REPO_ROOT", tmp_path)

    with pytest.raises(LaunchError, match="npm --prefix apps/web ci"):
        metis_dev.web_services()


@pytest.mark.usefixtures("repo_with_web_deps")
def test_web_services_run_the_api_with_this_python(monkeypatch):
    monkeypatch.setattr(metis_dev.shutil, "which", lambda name: f"/bin/{name}")

    api, web = metis_dev.web_services()

    assert api.argv[0] == sys.executable
    assert api.env == {"HOST": "127.0.0.1", "PORT": "8001"}
    assert api.ready_url == "http://127.0.0.1:8001/"
    assert web.argv[:2] == ["/bin/npm", "--prefix"]
