"""The development launcher runs real child processes, so these tests use small Python services."""

from __future__ import annotations

import socket
import sys
import time

import metis_dev
from metis_dev import Service, launch, run_services


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_service_that_stops_stops_the_others(capsys):
    started = time.monotonic()
    code = run_services(
        [
            Service("long", _python("print('hello'); import time; time.sleep(60)")),
            Service("short", _python("import time; time.sleep(0.5)")),
        ]
    )

    out = capsys.readouterr().out
    assert code == 1
    assert time.monotonic() - started < 15
    assert "long | hello" in out
    assert "[run] short stopped. Stopping the other servers." in out


def test_next_service_starts_after_ready_url_answers(capsys):
    port = _free_port()
    first = _python(
        "import http.server, time; time.sleep(1); print('serving', flush=True); "
        f"http.server.HTTPServer(('127.0.0.1', {port}), "
        "http.server.SimpleHTTPRequestHandler).serve_forever()"
    )

    run_services(
        [
            Service("first", first, ready_url=f"http://127.0.0.1:{port}/"),
            Service(
                "second", _python("import time; time.sleep(0.5); print('started')")
            ),
        ]
    )

    out = capsys.readouterr().out
    assert out.index("first | serving") < out.index("second | started")


def test_next_service_never_starts_when_the_first_stops_before_ready(capsys):
    code = run_services(
        [
            Service(
                "api",
                _python("raise SystemExit(3)"),
                ready_url=f"http://127.0.0.1:{_free_port()}/",
            ),
            Service("web", _python("print('must not start')")),
        ]
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "[run] api stopped." in out
    assert "must not start" not in out


def test_missing_npm_prints_one_error(monkeypatch, capsys):
    monkeypatch.setattr(metis_dev.shutil, "which", lambda name: None)

    assert launch(metis_dev.web_services) == 1
    assert "`npm` is not on PATH. Install Node.js" in capsys.readouterr().out
