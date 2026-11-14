"""Start several development servers from one command, on Windows, macOS, and Linux.

Each service gets its own process group. The launcher prefixes each output line with the
service label. Ctrl-C stops all services, and a service that exits on its own stops the others,
so no server stays behind to hold a port. A service with a `ready_url` holds back the next
service until that URL answers.

`metis web` starts the API and the web dev server. `python metis_dev.py site` starts the docs
and the landing page.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from metis.core.console import console

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent
API_PORT = 8001
WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class Service:
    label: str
    argv: Sequence[str]
    env: Mapping[str, str] = field(default_factory=dict)
    ready_url: str | None = None


class LaunchError(RuntimeError):
    """A service cannot start, for example because a required program is not installed."""


def require_program(name: str, hint: str) -> str:
    """Return the full path of `name`. On Windows this finds `npm.cmd` for `npm`."""
    path = shutil.which(name)
    if path is None:
        raise LaunchError(f"`{name}` is not on PATH. {hint}")
    return path


def web_services() -> list[Service]:
    npm = require_program("npm", "Install Node.js, which includes npm.")
    if not (REPO_ROOT / "apps" / "web" / "node_modules").is_dir():
        raise LaunchError(
            "The web dependencies are not installed. Run `npm --prefix apps/web ci` "
            "(or `make install-web`) in the repository folder."
        )
    return [
        Service(
            "api",
            [sys.executable, "-c", "from metis.api.cli import main; main()"],
            env={"HOST": "127.0.0.1", "PORT": str(API_PORT)},
            ready_url=f"http://127.0.0.1:{API_PORT}/",
        ),
        Service(
            "web", [npm, "--prefix", str(REPO_ROOT / "apps" / "web"), "run", "dev"]
        ),
    ]


def site_services() -> list[Service]:
    npm = require_program("npm", "Install Node.js, which includes npm.")
    pnpm = require_program(
        "pnpm", "Install pnpm, for example with `npm install -g pnpm`."
    )
    return [
        Service(
            "docs",
            [npm, "--prefix", str(REPO_ROOT / "website"), "start"],
            ready_url="http://127.0.0.1:3000/metis/docs/",
        ),
        Service(
            "landing",
            [pnpm, "--dir", str(REPO_ROOT / "website" / "landing-page"), "dev"],
        ),
    ]


def _start(service: Service) -> subprocess.Popen[bytes]:
    # A separate process group lets the launcher stop each whole tree. On Windows it also keeps
    # `npm.cmd` from asking "Terminate batch job (Y/N)?" after Ctrl-C.
    return subprocess.Popen(
        service.argv,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1", **service.env},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=not WINDOWS,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if sys.platform == "win32"
        else 0,
    )


def _relay(label: str, stream: IO[bytes]) -> None:
    for raw in stream:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        console.out(f"{label} | {line}", highlight=False)


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if not WINDOWS:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):  # noqa: S310 — a fixed local URL
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def _interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


_STOP_SIGNALS = [
    getattr(signal, name)
    for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")
    if hasattr(signal, name)
]


def _handle_stop_signals(handler: Any) -> dict[int, Any]:
    """Set `handler` for every stop signal and return the previous handlers."""
    if threading.current_thread() is not threading.main_thread():
        return {}
    return {sig: signal.signal(sig, handler) for sig in _STOP_SIGNALS}


class _Stopped(Exception):
    def __init__(self, label: str) -> None:
        self.label = label


def run_services(services: Sequence[Service], *, poll_seconds: float = 0.2) -> int:
    """Run `services` until one stops (exit code 1) or the user presses Ctrl-C (exit code 0)."""
    running: list[tuple[Service, subprocess.Popen[bytes]]] = []
    relays: list[threading.Thread] = []
    # Closing the terminal or `kill` must also stop the servers, as Ctrl-C does.
    previous = _handle_stop_signals(_interrupt)

    def check_running() -> None:
        for service, proc in running:
            if proc.poll() is not None:
                raise _Stopped(service.label)

    try:
        for service in services:
            proc = _start(service)
            running.append((service, proc))
            assert proc.stdout is not None
            relay = threading.Thread(
                target=_relay, args=(service.label, proc.stdout), daemon=True
            )
            relay.start()
            relays.append(relay)
            while service.ready_url and not _answers(service.ready_url):
                check_running()
                time.sleep(poll_seconds)
        while True:
            check_running()
            time.sleep(poll_seconds)
    except _Stopped as stopped:
        console.out(
            f"\n[run] {stopped.label} stopped. Stopping the other servers.",
            highlight=False,
        )
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        # `uv run` passes Ctrl-C on to the launcher a second time. That signal must not cut the
        # cleanup short and leave a server behind.
        _handle_stop_signals(signal.SIG_IGN)
        for _, proc in running:
            _stop(proc)
        for relay in relays:
            relay.join(timeout=2)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def launch(build: Callable[[], list[Service]]) -> int:
    """Build the services and run them. A missing prerequisite prints one error line."""
    try:
        services = build()
    except LaunchError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    return run_services(services)


PRESETS = {"web": web_services, "site": site_services}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in PRESETS:
        console.print(f"usage: python metis_dev.py {{{'|'.join(PRESETS)}}}")
        sys.exit(2)
    sys.exit(launch(PRESETS[sys.argv[1]]))
