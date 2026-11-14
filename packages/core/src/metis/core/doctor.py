"""`metis doctor`: check the local environment before a run.

Every check runs even after one fails, so a user fixes everything in one pass. A check reports
variable names and service names, never values. The two connectivity checks make one
authenticated call each, with a short timeout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

import httpx

from metis.core.model_settings import METIS_INTERNAL_LANGFUSE_VARS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

TIMEOUT_SECONDS = 5.0
"""Per call. Two calls keep the whole check under the 10 second budget."""

DEFAULT_GATEWAY_URL = "https://api.openai.com/v1"

REQUIRED_VARS = ("OPENAI_API_KEY",)

LANGFUSE_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
"""Only `metis engine evaluate` reads them, so a missing one is a warning, not a failure."""

INSTALLED_PACKAGES = (
    "metis-core",
    "metis-library",
    "metis-engine",
    "metis-wizard",
    "metis-insights",
)
"""The packages `metis_cli.py` imports at start. A CLI user does not need `metis-api`."""


class DoctorStatus(StrEnum):
    """How one check went. A warning or a skip does not fail the run."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass(frozen=True)
class DoctorResult:
    """The result of one check. `run_doctor()` returns one per check, in display order."""

    name: str
    status: DoctorStatus
    detail: str
    fix: str | None = None
    """A one-line fix, shown for a failure or a warning."""


def check_required_vars(env: Mapping[str, str]) -> list[DoctorResult]:
    """One result per required variable. An empty value counts as unset."""
    results: list[DoctorResult] = []
    for name in REQUIRED_VARS:
        if env.get(name):
            results.append(DoctorResult(name, DoctorStatus.PASS, "set"))
        else:
            results.append(
                DoctorResult(
                    name,
                    DoctorStatus.FAIL,
                    "not set",
                    f"Set {name} in .env (see .env.example).",
                )
            )
    return results


def check_langfuse_vars(env: Mapping[str, str]) -> list[DoctorResult]:
    """One result per `LANGFUSE_*` variable. A missing one warns that `evaluate` cannot run."""
    results: list[DoctorResult] = []
    for name in LANGFUSE_VARS:
        if env.get(name):
            results.append(DoctorResult(name, DoctorStatus.PASS, "set"))
        else:
            results.append(
                DoctorResult(
                    name,
                    DoctorStatus.WARN,
                    "not set, so you cannot run `metis engine evaluate`",
                    f"Set {name} in .env to grade a run.",
                )
            )
    return results


def check_internal_langfuse(env: Mapping[str, str]) -> DoctorResult:
    """The METIS-internal trio is all-or-nothing: a partly set trio leaves tracing off."""
    names = METIS_INTERNAL_LANGFUSE_VARS
    missing = [n for n in names if not env.get(n)]
    if len(missing) == len(names):
        return DoctorResult(
            "METIS-internal Langfuse", DoctorStatus.PASS, "not set (tracing off)"
        )
    if missing:
        return DoctorResult(
            "METIS-internal Langfuse",
            DoctorStatus.WARN,
            f"partly set, so tracing stays off. Missing: {', '.join(missing)}",
            "Set all three METIS_INTERNAL_LANGFUSE_* variables, or none.",
        )
    return DoctorResult(
        "METIS-internal Langfuse", DoctorStatus.PASS, "set (tracing on)"
    )


def check_install() -> list[DoctorResult]:
    """The METIS packages are installed and report a version."""
    results: list[DoctorResult] = []
    for package in INSTALLED_PACKAGES:
        try:
            results.append(
                DoctorResult(package, DoctorStatus.PASS, f"version {version(package)}")
            )
        except PackageNotFoundError:
            results.append(
                DoctorResult(
                    package,
                    DoctorStatus.FAIL,
                    "not installed",
                    "Run `make install` from the repository root.",
                )
            )
    return results


def _http_get(
    service: str,
    url: str,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
) -> DoctorResult:
    """One authenticated GET. Reports the status code or the error class, never a value."""
    name = f"{service} connection"
    try:
        response = httpx.get(
            url,
            headers=headers,
            auth=auth,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except httpx.TimeoutException:
        return DoctorResult(
            name,
            DoctorStatus.FAIL,
            f"timed out after {TIMEOUT_SECONDS:g}s",
            f"Check the {service} URL and your network.",
        )
    except httpx.HTTPError as exc:
        return DoctorResult(
            name,
            DoctorStatus.FAIL,
            f"could not connect ({type(exc).__name__})",
            f"Check the {service} URL and your network.",
        )
    if response.is_success:
        return DoctorResult(name, DoctorStatus.PASS, "authenticated")
    if response.status_code in (401, 403):
        return DoctorResult(
            name,
            DoctorStatus.FAIL,
            f"rejected the key (HTTP {response.status_code})",
            f"Check the {service} key in .env.",
        )
    return DoctorResult(
        name,
        DoctorStatus.FAIL,
        f"unexpected response (HTTP {response.status_code})",
        f"Check the {service} URL in .env.",
    )


def check_gateway(env: Mapping[str, str]) -> DoctorResult:
    """List models on the shared gateway with ``OPENAI_API_KEY``."""
    key = env.get("OPENAI_API_KEY")
    if not key:
        return DoctorResult(
            "Model gateway connection", DoctorStatus.SKIP, "OPENAI_API_KEY is not set"
        )
    base = (env.get("OPENAI_BASE_URL") or DEFAULT_GATEWAY_URL).rstrip("/")
    return _http_get(
        "Model gateway", f"{base}/models", headers={"Authorization": f"Bearer {key}"}
    )


def check_langfuse(env: Mapping[str, str]) -> DoctorResult:
    """Read the project list from Langfuse with the public and secret keys."""
    public, secret, base = (
        env.get("LANGFUSE_PUBLIC_KEY"),
        env.get("LANGFUSE_SECRET_KEY"),
        env.get("LANGFUSE_BASE_URL"),
    )
    if not (public and secret and base):
        return DoctorResult(
            "Langfuse connection",
            DoctorStatus.SKIP,
            "a LANGFUSE_* variable is not set",
        )
    return _http_get(
        "Langfuse", f"{base.rstrip('/')}/api/public/projects", auth=(public, secret)
    )


def run_doctor(env: Mapping[str, str] | None = None) -> list[DoctorResult]:
    """Run every check and return the results in display order."""
    env = os.environ if env is None else env
    steps: list[Callable[[], list[DoctorResult] | DoctorResult]] = [
        lambda: check_install(),
        lambda: check_required_vars(env),
        lambda: check_langfuse_vars(env),
        lambda: check_internal_langfuse(env),
        lambda: check_gateway(env),
        lambda: check_langfuse(env),
    ]
    results: list[DoctorResult] = []
    for step in steps:
        outcome = step()
        results.extend(outcome if isinstance(outcome, list) else [outcome])
    return results


_STYLE = {
    DoctorStatus.PASS: ("[green]pass[/green]", ""),
    DoctorStatus.FAIL: ("[red]FAIL[/red]", ""),
    DoctorStatus.WARN: ("[yellow]warn[/yellow]", ""),
    DoctorStatus.SKIP: ("[dim]skip[/dim]", ""),
}


def report(results: list[DoctorResult]) -> bool:
    """Print one line per check, with the fix under each failure or warning.

    Returns True when no required check failed. A warning or a skip does not fail the run.
    """
    from rich.markup import escape

    from metis.core.console import console

    for result in results:
        label, _ = _STYLE[result.status]
        console.print(f"{label}  {escape(result.name)}: {escape(result.detail)}")
        if result.fix and result.status in (DoctorStatus.FAIL, DoctorStatus.WARN):
            console.print(f"      fix: {escape(result.fix)}")
    failed = [r for r in results if r.status is DoctorStatus.FAIL]
    if failed:
        console.print(f"\n[red]{len(failed)} check(s) failed.[/red]")
    else:
        console.print("\n[green]Environment is ready.[/green]")
    return not failed
