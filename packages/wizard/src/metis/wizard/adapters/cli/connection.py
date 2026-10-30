"""CLI input for the target connection: the mode, the transport, and the binding values.

Each secret field takes the name of an environment variable, never its value. The CLI runs the
live check on the user's computer, so it reads the user's own environment.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import yaml

from metis.wizard.adapters.cli.keys import (
    BACK,
    Choice,
    Nav,
    Prompter,
    Step,
    TextPrompter,
    Typed,
    walk,
)
from metis.wizard.application.connection import check_connection
from metis.wizard.contracts.connection import (
    ConnectionCheckResult,
    ConnectionStatus,
    TargetConnection,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import httpx

Printer = Callable[[str], None]
Reader = Callable[[str], str]
Mode = Literal["spec", "run"]

_SECRET_NOTE = "Secret fields take a variable name. Set its value in .env."


def panel(title: str, body: str = "") -> str:
    """A titled panel as text, in the same style as the Interview step headers."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    with console.capture() as capture:
        console.print(Panel(body, title=title, title_align="left"))
    return capture.get().rstrip("\n")


def rule() -> str:
    """A rule that separates a screen's content from its choices."""
    from rich.console import Console
    from rich.rule import Rule

    console = Console()
    with console.capture() as capture:
        console.print(Rule())
    return capture.get().rstrip("\n")


def _ask(prompter: Prompter | None, out: Printer, read: Reader) -> Prompter:
    return prompter if prompter is not None else TextPrompter(out, read)


def read_mode(
    *,
    out: Printer,
    read: Reader = input,
    prompter: Prompter | None = None,
    default: Mode = "spec",
    back: bool = False,
) -> Mode | Nav:
    """Ask whether to make a Specification only, or also connect a target to run it.

    Esc returns `BACK` when `back` allows it.
    """
    out(panel("Mode", "What do you want to do?"))
    choices: list[Choice[Mode]] = [
        Choice("spec", "Build Spec only", aliases=("spec",)),
        Choice(
            "run", "Build Spec and Run Evals (connect the target)", aliases=("run",)
        ),
    ]
    return _ask(prompter, out, read).choose(
        choices, name="Mode", default=default, back=back
    )


def read_binding_source(
    *,
    out: Printer,
    read: Reader = input,
    prompter: Prompter | None = None,
    back: bool = False,
    default: Path | None = None,
) -> Path | None | Nav:
    """Ask how to give the binding: in the CLI, or as a file path. Returns the path, if any.

    Esc on the file path asks the binding source again. Esc on the binding source returns
    `BACK` when `back` allows it.
    """
    from pathlib import Path

    ask = _ask(prompter, out, read)
    choices = [
        Choice("fields", "Fill in the fields here"),
        Choice("file", "Give the path to a binding YAML file"),
    ]
    source = "fields" if default is None else "file"
    while True:
        out("\nHow do you want to give the target binding?")
        source = ask.choose(choices, name="Binding", default=source, back=back)
        if source is BACK:
            return BACK
        if source == "fields":
            return None
        while True:
            raw = ask.text("Binding file path", str(default or ""), back=True)
            if raw is BACK:
                break
            assert isinstance(raw, str)
            path = Path(raw).expanduser()
            if raw and path.is_file():
                return path
            out("  No file at that path. Enter the path to a binding YAML file.")


def load_binding_file(path: Path) -> dict[str, Any]:
    """Read binding values from a YAML file. The values are checked later."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a target binding mapping")
    return data


def read_target_connection(
    *,
    out: Printer,
    read: Reader = input,
    prompter: Prompter | None = None,
    values: Mapping[str, Any] | None = None,
    interactive: bool = True,
    back: bool = False,
    draft: dict[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[[bool], httpx.Client] | None = None,
) -> TargetConnection | None | Nav:
    """Read and test binding values until the binding is valid and the user continues.

    Run mode needs a valid binding, so there is no skip. A failed live test (for example the
    server is down) is a warning only, because the engine runs later, maybe somewhere else.

    :param values: Binding values to test first, for example from `--binding`.
    :param interactive: When false, test `values` once and ask nothing.
    :param back: Whether Esc on the first question returns `BACK`.
    :param draft: The answers to the binding fields. The caller keeps it, so the fields keep
        the answers when the user comes back to them.
    :returns: The connection, `None` when `values` is not valid and nothing can be asked, or
        `BACK`.
    """
    ask = _ask(prompter, out, read)
    out(panel("Target connection", _SECRET_NOTE))
    if values is not None:
        data = dict(values)
    else:
        first = _read_values(ask, out, {} if draft is None else draft, back=back)
        if first is BACK:
            return BACK
        data = first
    while True:
        result = check_connection(
            data, live=True, environ=environ, client_factory=client_factory
        )
        out(rule())
        _show(result, out)
        if not interactive:
            return result.connection()
        if result.binding is None:
            out("Fix the values. To continue without a binding, run with --mode spec.")
            data = _fix(ask, out, data)
            continue
        if _offer_suggestion(ask, out, result, data):
            data = {**data, "submissions": list(result.suggested_submissions)}
            continue
        choice = ask.choose(
            _NEXT,
            name="Next",
            default="continue",
            typed=Typed(
                "[t]est again, [f]ix the values, or [c]ontinue",
                "  Enter one of: t, f, c.",
            ),
        )
        if choice == "continue":
            if result.status is not ConnectionStatus.CHECKED:
                out(
                    "The export keeps this binding. review.md says that it was not tested."
                )
            return result.connection()
        if choice == "fix":
            data = _fix(ask, out, data)


_NEXT = [
    Choice("test", "Test again", aliases=("t",)),
    Choice("fix", "Fix the values", aliases=("f",)),
    Choice("continue", "Continue", aliases=("c",)),
]


def _offer_suggestion(
    ask: Prompter,
    out: Printer,
    result: ConnectionCheckResult,
    data: Mapping[str, Any],
) -> bool:
    """Show the submissions that the OpenAPI document suggests, and ask to use them.

    A document does not mark the chat message field, so the binding gets a suggestion only when
    the user says yes.
    """
    suggested = result.suggested_submissions
    if not suggested or sorted(suggested) == sorted(data.get("submissions") or []):
        return False
    out("\nThe OpenAPI document suggests these submissions:")
    for pattern in suggested:
        out(f"  {pattern}")
    return ask.confirm("Use them as the submissions?", False) is True


def _fix(ask: Prompter, out: Printer, data: Mapping[str, Any]) -> dict[str, Any]:
    """Ask the binding fields again, with the current values as defaults."""
    fixed = _read_values(ask, out, _answers(data))
    assert fixed is not BACK
    return fixed


def _show(result: ConnectionCheckResult, out: Printer) -> None:
    """Show field errors and live checks. Each message names a field or a variable only."""
    if result.errors:
        out("\nThe binding is not valid:")
        for error in result.errors:
            where = ".".join(str(part) for part in error.loc) or "binding"
            out(f"  - {where}: {error.msg}")
        return
    out("\nThe binding is valid.")
    for probe in result.probes:
        mark = "✓" if probe.ok else "✗"
        out(f"  {mark} {probe.name}: {probe.message}")
    for warning in result.warnings:
        out(f"  ⚠ {warning.msg}")


# ── binding values ────────────────────────────────────────────────────────
#
# The binding fields are a list of steps over one dict of answers, keyed by step name. Esc on
# a field asks the field before it again; Esc on the transport leaves the list.


def _is_http(answers: dict[str, Any]) -> bool:
    return answers.get("transport") == "http"


def _is_browser(answers: dict[str, Any]) -> bool:
    return answers.get("transport") == "browser"


def _field(
    ask: Prompter, name: str, label: str
) -> Callable[[dict[str, Any], bool], Any]:
    return lambda answers, back: ask.text(label, answers.get(name) or "", back=back)


def _list_field(
    ask: Prompter, name: str, label: str
) -> Callable[[dict[str, Any], bool], Any]:
    def run(answers: dict[str, Any], back: bool) -> list[str] | Nav:
        raw = ask.text(label, ", ".join(answers.get(name) or []), back=back)
        if raw is BACK:
            return BACK
        assert isinstance(raw, str)
        return [item.strip() for item in raw.split(",") if item.strip()]

    return run


def _binding_steps(ask: Prompter, out: Printer) -> list[Step]:
    def transport(answers: dict[str, Any], back: bool) -> Any:
        out("\nHow does METIS reach the target?")
        choices = [
            Choice(
                "http",
                "HTTP API (the target has an OpenAPI document)",
                aliases=("http",),
            ),
            Choice(
                "browser",
                "Browser (the target has only a web page)",
                aliases=("browser",),
            ),
        ]
        default = answers.get("transport") or "http"
        return ask.choose(choices, name="Transport", default=default, back=back)

    def tls(answers: dict[str, Any], back: bool) -> Any:
        default = answers.get("tls_verify", True)
        return ask.confirm("Verify the TLS certificate?", default, back=back)

    def headers(answers: dict[str, Any], back: bool) -> Any:
        return _read_secret_headers(ask, out, answers.get("headers") or [], back)

    def with_note(answers: dict[str, Any]) -> bool:
        return _is_browser(answers) and bool(answers.get("login_note"))

    return [
        Step("transport", transport),
        Step("name", _field(ask, "name", "Target name")),
        Step(
            "spec_url",
            _field(ask, "spec_url", "OpenAPI document URL (${NAME} reads a variable)"),
            _is_http,
        ),
        Step(
            "secret_env",
            _field(
                ask,
                "secret_env",
                "Environment variable that holds the API credential (blank for none)",
            ),
            _is_http,
        ),
        Step("headers", headers, _is_http),
        Step(
            "forbidden",
            _list_field(
                ask,
                "forbidden",
                "Calls the engine must refuse, as METHOD /path (comma-separated)",
            ),
            _is_http,
        ),
        Step(
            "submissions",
            _list_field(
                ask,
                "submissions",
                "Calls that send the user's message (comma-separated; blank for any POST, PUT, or PATCH)",
            ),
            _is_http,
        ),
        Step("tls_verify", tls, _is_http),
        Step(
            "start_url",
            _field(ask, "start_url", "Start page URL (${NAME} reads a variable)"),
            _is_browser,
        ),
        Step(
            "login_note",
            _field(
                ask,
                "login_note",
                "Sign-in steps, with {{secret:NAME}} where a secret is typed (blank for none)",
            ),
            _is_browser,
        ),
        Step(
            "login_secrets",
            _list_field(
                ask,
                "login_secrets",
                "Environment variables that the sign-in types (comma-separated)",
            ),
            with_note,
        ),
        Step(
            "notes", _field(ask, "notes", "Notes for the runner agent (blank for none)")
        ),
    ]


def _read_values(
    ask: Prompter, out: Printer, answers: dict[str, Any], *, back: bool = False
) -> dict[str, Any] | Nav:
    """Ask for the values that the target cannot supply. Enter keeps the current value."""
    if not walk(_binding_steps(ask, out), answers, back=back):
        return BACK
    return _binding(answers)


def _binding(answers: dict[str, Any]) -> dict[str, Any]:
    """The binding values from the answers to the steps that apply."""
    data: dict[str, Any] = {
        "schema_version": 1,
        "identity": {"name": answers.get("name", "")},
        "transport": answers["transport"],
    }
    if _is_http(answers):
        data["spec_url"] = answers.get("spec_url", "")
        if answers.get("secret_env"):
            data["auth"] = {"secret_env": answers["secret_env"]}
        for key, name in (
            ("secret_headers", "headers"),
            ("forbidden_calls", "forbidden"),
            ("submissions", "submissions"),
        ):
            if answers.get(name):
                data[key] = answers[name]
        if answers.get("tls_verify") is False:
            data["tls_verify"] = False
    else:
        data["start_url"] = answers.get("start_url", "")
        if answers.get("login_note"):
            data["login"] = {
                "note": answers["login_note"],
                "secrets": answers.get("login_secrets") or [],
            }
    if answers.get("notes"):
        data["advice"] = {"notes": answers["notes"]}
    return data


def _answers(data: Mapping[str, Any]) -> dict[str, Any]:
    """The step answers that give these binding values, used as defaults for a fix."""
    identity = data.get("identity") or {}
    auth = data.get("auth") or {}
    login = data.get("login") or {}
    advice = data.get("advice") or {}
    return {
        "transport": "browser" if data.get("transport") == "browser" else "http",
        "name": identity.get("name"),
        "spec_url": data.get("spec_url"),
        "secret_env": auth.get("secret_env"),
        "headers": data.get("secret_headers") or [],
        "forbidden": data.get("forbidden_calls"),
        "submissions": data.get("submissions"),
        "tls_verify": data.get("tls_verify") is not False,
        "start_url": data.get("start_url"),
        "login_note": login.get("note"),
        "login_secrets": login.get("secrets"),
        "notes": advice.get("notes"),
    }


def _read_secret_headers(
    ask: Prompter, out: Printer, current: list[dict[str, Any]], back: bool
) -> list[dict[str, Any]] | Nav:
    if current:
        out(f"  {len(current)} secret header(s) are set.")
        keep = ask.confirm("Keep them?", True, back=back)
        if keep is BACK:
            return BACK
        if keep:
            return current
    headers: list[dict[str, Any]] = []
    out(
        "Secret headers: one per line as METHOD /path HEADER ENV_NAME, "
        "for example `POST /chat X-Api-Key APP_KEY`. Blank to finish."
    )
    while True:
        raw = ask.text("Secret header", back=back)
        if raw is BACK:
            return BACK
        assert isinstance(raw, str)
        if not raw:
            return headers
        parts = raw.split()
        if len(parts) != 4:
            out("  Enter four parts: METHOD /path HEADER ENV_NAME.")
            continue
        method, path, header, env = parts
        headers.append({"match": f"{method} {path}", "header": header, "env": env})


__all__ = [
    "load_binding_file",
    "read_binding_source",
    "read_mode",
    "read_target_connection",
]
