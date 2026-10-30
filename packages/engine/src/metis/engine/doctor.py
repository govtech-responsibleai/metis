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

INSTALLED_PACKAGES = ("metis-core", "metis-library", "metis-engine")


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str | None = None
    """A one-line fix, shown for a failure or a warning."""


def check_required_vars(env: Mapping[str, str]) -> list[CheckResult]:
    """One result per required variable. An empty value counts as unset."""
    results: list[CheckResult] = []
    for name in REQUIRED_VARS:
        if env.get(name):
            results.append(CheckResult(name, Status.PASS, "set"))
        else:
            results.append(
                CheckResult(
                    name,
                    Status.FAIL,
                    "not set",
                    f"Set {name} in .env (see .env.example).",
                )
            )
    return results


def check_langfuse_vars(env: Mapping[str, str]) -> list[CheckResult]:
    """One result per `LANGFUSE_*` variable. A missing one warns that `evaluate` cannot run."""
    results: list[CheckResult] = []
    for name in LANGFUSE_VARS:
        if env.get(name):
            results.append(CheckResult(name, Status.PASS, "set"))
        else:
            results.append(
                CheckResult(
                    name,
                    Status.WARN,
                    "not set, so you cannot run `metis engine evaluate`",
                    f"Set {name} in .env to grade a run.",
                )
            )
    return results


def check_internal_langfuse(env: Mapping[str, str]) -> CheckResult:
    """The METIS-internal trio is all-or-nothing: a partly set trio leaves tracing off."""
    names = METIS_INTERNAL_LANGFUSE_VARS
    missing = [n for n in names if not env.get(n)]
    if len(missing) == len(names):
        return CheckResult(
            "METIS-internal Langfuse", Status.PASS, "not set (tracing off)"
        )
    if missing:
        return CheckResult(
            "METIS-internal Langfuse",
            Status.WARN,
            f"partly set, so tracing stays off. Missing: {', '.join(missing)}",
            "Set all three METIS_INTERNAL_LANGFUSE_* variables, or none.",
        )
    return CheckResult("METIS-internal Langfuse", Status.PASS, "set (tracing on)")


def check_install() -> list[CheckResult]:
    """The METIS packages are installed and report a version."""
    results: list[CheckResult] = []
    for package in INSTALLED_PACKAGES:
        try:
            results.append(
                CheckResult(package, Status.PASS, f"version {version(package)}")
            )
        except PackageNotFoundError:
            results.append(
                CheckResult(
                    package,
                    Status.FAIL,
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
) -> CheckResult:
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
        return CheckResult(
            name,
            Status.FAIL,
            f"timed out after {TIMEOUT_SECONDS:g}s",
            f"Check the {service} URL and your network.",
        )
    except httpx.HTTPError as exc:
        return CheckResult(
            name,
            Status.FAIL,
            f"could not connect ({type(exc).__name__})",
            f"Check the {service} URL and your network.",
        )
    if response.is_success:
        return CheckResult(name, Status.PASS, "authenticated")
    if response.status_code in (401, 403):
        return CheckResult(
            name,
            Status.FAIL,
            f"rejected the key (HTTP {response.status_code})",
            f"Check the {service} key in .env.",
        )
    return CheckResult(
        name,
        Status.FAIL,
        f"unexpected response (HTTP {response.status_code})",
        f"Check the {service} URL in .env.",
    )


def check_gateway(env: Mapping[str, str]) -> CheckResult:
    """List models on the shared gateway with ``OPENAI_API_KEY``."""
    key = env.get("OPENAI_API_KEY")
    if not key:
        return CheckResult(
            "Model gateway connection", Status.SKIP, "OPENAI_API_KEY is not set"
        )
    base = (env.get("OPENAI_BASE_URL") or DEFAULT_GATEWAY_URL).rstrip("/")
    return _http_get(
        "Model gateway", f"{base}/models", headers={"Authorization": f"Bearer {key}"}
    )


def check_langfuse(env: Mapping[str, str]) -> CheckResult:
    """Read the project list from Langfuse with the public and secret keys."""
    public, secret, base = (
        env.get("LANGFUSE_PUBLIC_KEY"),
        env.get("LANGFUSE_SECRET_KEY"),
        env.get("LANGFUSE_BASE_URL"),
    )
    if not (public and secret and base):
        return CheckResult(
            "Langfuse connection",
            Status.SKIP,
            "a LANGFUSE_* variable is not set",
        )
    return _http_get(
        "Langfuse", f"{base.rstrip('/')}/api/public/projects", auth=(public, secret)
    )


def run_checks(env: Mapping[str, str] | None = None) -> list[CheckResult]:
    """Run every check and return the results in display order."""
    env = os.environ if env is None else env
    steps: list[Callable[[], list[CheckResult] | CheckResult]] = [
        lambda: check_install(),
        lambda: check_required_vars(env),
        lambda: check_langfuse_vars(env),
        lambda: check_internal_langfuse(env),
        lambda: check_gateway(env),
        lambda: check_langfuse(env),
    ]
    results: list[CheckResult] = []
    for step in steps:
        outcome = step()
        results.extend(outcome if isinstance(outcome, list) else [outcome])
    return results


_STYLE = {
    Status.PASS: ("[green]pass[/green]", ""),
    Status.FAIL: ("[red]FAIL[/red]", ""),
    Status.WARN: ("[yellow]warn[/yellow]", ""),
    Status.SKIP: ("[dim]skip[/dim]", ""),
}


def report(results: list[CheckResult]) -> bool:
    """Print one line per check, with the fix under each failure or warning.

    Returns True when no required check failed. A warning or a skip does not fail the run.
    """
    from rich.markup import escape

    from metis.core.console import console

    for result in results:
        label, _ = _STYLE[result.status]
        console.print(f"{label}  {escape(result.name)}: {escape(result.detail)}")
        if result.fix and result.status in (Status.FAIL, Status.WARN):
            console.print(f"      fix: {escape(result.fix)}")
    failed = [r for r in results if r.status is Status.FAIL]
    if failed:
        console.print(f"\n[red]{len(failed)} check(s) failed.[/red]")
    else:
        console.print("\n[green]Environment is ready.[/green]")
    return not failed
