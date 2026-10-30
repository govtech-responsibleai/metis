"""Check a target binding and attach it to an Interview and its export.

The check has two tiers. Neither imports the engine.

- **Tier 1, offline, in every client.** `TargetBinding` validates the shape, including each
  `{{secret:NAME}}` placeholder in `login.note`. The Wizard also refuses a URL that holds a
  user name or password.
- **Tier 2, live.** The Wizard reports each environment variable that the binding names as set
  or not set, and reaches the target: for HTTP it fetches `spec_url` and reads the OpenAPI
  document; for a browser it loads `start_url`. The CLI runs it on the user's computer and
  expands each `${NAME}` in a URL from the user's environment. The API runs it by default only
  when it listens on this computer (`127.0.0.1`, `localhost`, or `::1`), and
  `METIS_API_CONNECTION_CHECK` overrides that. The API never expands a variable into a URL that
  it requests: a client could otherwise send a URL that carries a server secret to a host that
  the client controls. A URL that names a variable is reported as not checked.

No message repeats a value. A message names a field, a variable, a URL as written, or a status
code. It never holds an expanded URL, a variable's value, or a response body.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import httpx
import yaml
from pydantic import ValidationError

from metis.core.target_binding import TargetBinding, call_matches
from metis.wizard.application import export_layout
from metis.wizard.contracts.connection import (
    ConnectionCheckResult,
    ConnectionFieldError,
    ConnectionProbe,
    ConnectionStatus,
    ConnectionTransport,
    TargetConnection,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from metis.wizard.contracts.interview_state import InterviewState
    from metis.wizard.domain.specification import Specification

RUNNER_FACTORY_REFS: dict[ConnectionTransport, str] = {
    ConnectionTransport.HTTP: "metis.engine.simulation.runners.http.HttpRunnerFactory",
    ConnectionTransport.BROWSER: (
        "metis.engine.simulation.runners.browser.BrowserRunnerFactory"
    ),
}
"""The generic runner factory for each transport, as FQN strings. The Wizard never imports them."""

TARGET_BINDING_FILE = export_layout.TARGET_BINDING.name
"""The binding file name, relative to `specification.yaml`."""

_ENV_REFERENCE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
# scheme://anything@host — a user name or password written into the URL itself
_USERINFO = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]*@")
_TIMEOUT = httpx.Timeout(10.0)


def _default_client(tls_verify: bool) -> httpx.Client:
    """The HTTP client for the live check. Redirects are not followed, as in the engine."""
    return httpx.Client(verify=tls_verify, timeout=_TIMEOUT, follow_redirects=False)


# ── tier 1 ────────────────────────────────────────────────────────────────


def validate_binding(data: Mapping[str, Any]) -> ConnectionCheckResult:
    """Validate binding values offline. Errors give the field and the reason only."""
    try:
        binding = TargetBinding.model_validate(dict(data))
    except ValidationError as exc:
        return ConnectionCheckResult(errors=field_errors(exc))
    errors = [
        ConnectionFieldError(
            loc=[name],
            msg=(
                f"{name} must not hold a user name or password. Name an environment "
                "variable for the credential instead."
            ),
        )
        for name in ("spec_url", "start_url")
        if _USERINFO.match(getattr(binding, name) or "")
    ]
    if errors:
        return ConnectionCheckResult(errors=errors)
    return ConnectionCheckResult(binding=binding)


def field_errors(exc: ValidationError) -> list[ConnectionFieldError]:
    """Convert a validation error to field errors without the rejected input."""
    return [
        ConnectionFieldError(loc=[*error["loc"]], msg=error["msg"])
        for error in exc.errors(include_input=False, include_url=False)
    ]


# ── tier 2 ────────────────────────────────────────────────────────────────


def check_connection(
    data: Mapping[str, Any],
    *,
    live: bool,
    expand_variables: bool = True,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[[bool], httpx.Client] | None = None,
) -> ConnectionCheckResult:
    """Validate the binding, and with `live`, check the environment and reach the target.

    :param expand_variables: Put each `${NAME}` value from `environ` into a URL before the
        request. The CLI expands, because the environment is the user's own. The API does not,
        because the environment is the server's and the URL comes from a client. With `False`,
        a URL that names a variable is not requested.
    :param environ: The environment to read variables from. The default is `os.environ`.
    :param client_factory: Builds the HTTP client from `tls_verify`. Tests supply a client on
        `httpx.MockTransport`.
    """
    result = validate_binding(data)
    if not live or result.binding is None:
        return result
    probes, document = live_probes(
        result.binding,
        expand_variables=expand_variables,
        environ=os.environ if environ is None else environ,
        client_factory=client_factory or _default_client,
    )
    status = (
        ConnectionStatus.CHECKED
        if all(probe.ok for probe in probes)
        else ConnectionStatus.UNCHECKED
    )
    update: dict[str, Any] = {"live": True, "probes": probes, "status": status}
    if document is not None:
        update["suggested_submissions"] = suggest_submissions(document)
        update["warnings"] = submission_warnings(result.binding.submissions, document)
    return result.model_copy(update=update)


def live_probes(
    binding: TargetBinding,
    *,
    environ: Mapping[str, str],
    client_factory: Callable[[bool], httpx.Client],
    expand_variables: bool = True,
) -> tuple[list[ConnectionProbe], dict[str, Any] | None]:
    """Report each named variable as set or not set, then try to reach the target.

    :returns: The probes, and the OpenAPI document when the check read one.
    """
    probes = _variable_probes(binding, environ)
    # `None` keeps every `${NAME}` value out of the URLs that the check requests
    url_environ = environ if expand_variables else None
    if binding.transport == "http":
        fetched, document = _fetch_openapi(
            binding.spec_url or "", binding.tls_verify, url_environ, client_factory
        )
        return probes + fetched, document
    probes.append(
        _load_start_page(binding.start_url or "", url_environ, client_factory)
    )
    return probes, None


def required_variables(binding: TargetBinding) -> list[str]:
    """The environment variables that the engine needs, in the order the binding names them."""
    names: list[str] = []
    for url in (binding.spec_url, binding.start_url):
        names.extend(_ENV_REFERENCE.findall(url or ""))
    if binding.auth is not None:
        names.append(binding.auth.secret_env)
    if binding.login is not None:
        names.extend(binding.login.secrets)
    return list(dict.fromkeys(names))


def optional_variables(binding: TargetBinding) -> list[str]:
    """Variables for secret headers. The engine leaves out a header whose variable is not set."""
    required = set(required_variables(binding))
    return list(
        dict.fromkeys(h.env for h in binding.secret_headers if h.env not in required)
    )


def _variable_probes(
    binding: TargetBinding, environ: Mapping[str, str]
) -> list[ConnectionProbe]:
    probes = [
        ConnectionProbe(
            name=name,
            ok=bool(environ.get(name)),
            message="set" if environ.get(name) else "not set",
        )
        for name in required_variables(binding)
    ]
    probes += [
        ConnectionProbe(
            name=name,
            ok=True,
            message="set"
            if environ.get(name)
            else "not set; the engine leaves this header out",
        )
        for name in optional_variables(binding)
    ]
    return probes


def _expand(
    written: str, environ: Mapping[str, str] | None
) -> tuple[str | None, str | None]:
    """The URL with `${NAME}` expanded, or why the check does not request it.

    With `environ` as `None`, a URL that names a variable is not requested, so no variable's
    value goes into a request.
    """
    names = _ENV_REFERENCE.findall(written)
    if environ is None:
        if names:
            return None, (
                f"the URL names {names[0]}, so the API does not request it. "
                "Run `metis wizard connect` to check it with your environment"
            )
        return written, None
    for name in names:
        if not environ.get(name):
            return None, f"{name} is not set"
    return _ENV_REFERENCE.sub(lambda match: environ[match.group(1)], written), None


def _fetch_openapi(
    written: str,
    tls_verify: bool,
    environ: Mapping[str, str] | None,
    client_factory: Callable[[bool], httpx.Client],
) -> tuple[list[ConnectionProbe], dict[str, Any] | None]:
    """Fetch the OpenAPI document, then check that its server answers.

    The server check sends one HEAD request to the server root. It calls no endpoint of the API,
    so it cannot change the target's data. Only the engine sends real calls.
    """
    probe = "spec_url"
    url, reason = _expand(written, environ)
    if url is None:
        return [
            ConnectionProbe(name=probe, ok=False, message=f"not fetched: {reason}")
        ], None
    if urlsplit(url).scheme.lower() not in ("http", "https"):
        return [
            ConnectionProbe(
                name=probe,
                ok=False,
                message=(
                    f"{written!r} is not an http(s) URL. The Wizard checks only http(s) "
                    f"URLs. For a file, put it next to {TARGET_BINDING_FILE} before you run."
                ),
            )
        ], None
    try:
        with client_factory(tls_verify) as client:
            response = client.get(url)
            if not response.is_success:
                return [
                    ConnectionProbe(
                        name=probe,
                        ok=False,
                        message=f"{written!r} returned HTTP {response.status_code}",
                    )
                ], None
            document, problem = _openapi_document(response.content, url)
            if document is None:
                return [
                    ConnectionProbe(
                        name=probe, ok=False, message=f"{written!r} {problem}"
                    )
                ], None
            server = _server_url(document, url)
            probes = [ConnectionProbe(name=probe, ok=True, message=_summary(document))]
            probes.append(_server_answers(client, server))
            return probes, document
    except httpx.HTTPError as exc:
        # the exception text can hold the expanded URL, so only its type is shown
        return [
            ConnectionProbe(
                name=probe,
                ok=False,
                message=f"could not fetch {written!r} ({type(exc).__name__})",
            )
        ], None


def _openapi_document(content: bytes, url: str) -> tuple[dict[str, Any] | None, str]:
    """The fetched document when the HTTP runner can use it, or why it cannot."""
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError:
        return None, "is not JSON or YAML"
    if not isinstance(document, dict):
        return None, "is not an OpenAPI document"
    if "openapi" not in document:
        return None, "has no `openapi` version, so it is not an OpenAPI document"
    if not isinstance(document.get("paths"), dict):
        return None, "has no `paths`"
    if not _server_url(document, url).startswith(("http://", "https://")):
        return None, "has a first server that is not an http(s) URL"
    return document, ""


def _server_url(document: Mapping[str, Any], url: str) -> str:
    """The same rule as the engine: the first server, joined to the document's URL."""
    servers = document.get("servers") or [{"url": "/"}]
    first = servers[0] if isinstance(servers, list) and servers else {}
    server = str(first.get("url") or "/") if isinstance(first, dict) else "/"
    return urljoin(url, server)


def _summary(document: Mapping[str, Any]) -> str:
    """For example `OpenAPI document: Billing API 2.0, 14 endpoints`."""
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    title = str(info.get("title") or "untitled API")
    version = f" {info['version']}" if info.get("version") else ""
    count = sum(
        1
        for item in document["paths"].values()
        if isinstance(item, dict)
        for method in item
        if method.lower() in _HTTP_METHODS
    )
    noun = "endpoint" if count == 1 else "endpoints"
    return f"OpenAPI document: {title}{version}, {count} {noun}"


_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch"})


def _server_answers(client: httpx.Client, server: str) -> ConnectionProbe:
    """Any HTTP response means the server is up. Only a failed connection is a problem."""
    # The server URL can hold an expanded `${NAME}` value, so the message does not show it.
    probe = "server"
    try:
        client.head(server)
    except httpx.HTTPError as exc:
        return ConnectionProbe(
            name=probe,
            ok=False,
            message=f"the server in the OpenAPI document did not answer ({type(exc).__name__})",
        )
    return ConnectionProbe(name=probe, ok=True, message="the API server answers")


def _load_start_page(
    written: str,
    environ: Mapping[str, str] | None,
    client_factory: Callable[[bool], httpx.Client],
) -> ConnectionProbe:
    probe = "start_url"
    url, reason = _expand(written, environ)
    if url is None:
        return ConnectionProbe(name=probe, ok=False, message=f"not loaded: {reason}")
    if urlsplit(url).scheme.lower() not in ("http", "https"):
        return ConnectionProbe(
            name=probe, ok=False, message=f"{written!r} is not an http(s) URL"
        )
    try:
        with client_factory(True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return ConnectionProbe(
            name=probe,
            ok=False,
            message=f"could not load {written!r} ({type(exc).__name__})",
        )
    if not 200 <= response.status_code < 400:
        return ConnectionProbe(
            name=probe,
            ok=False,
            message=f"{written!r} returned HTTP {response.status_code}",
        )
    return ConnectionProbe(
        name=probe,
        ok=True,
        message=f"{written!r} returned HTTP {response.status_code}",
    )


# ── submissions from the OpenAPI document ───────────────────────────────
#
# A document does not say which field is the chat message, so a suggestion is a hint that the
# user confirms. The engine reads only the binding file and infers nothing at run time.

_WRITE_METHODS = ("post", "put", "patch")
_PARAMETER = re.compile(r"\{[^{}]*\}")


def _operations(document: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Each `(METHOD, path, operation)` in the document, in document order."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in document["paths"].items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in _HTTP_METHODS and isinstance(operation, dict):
                found.append((method.upper(), path, operation))
    return found


def _resolve(document: Mapping[str, Any], schema: object) -> dict[str, Any]:
    """The schema, with one local `$ref` such as `#/components/schemas/Chat` followed."""
    if not isinstance(schema, dict):
        return {}
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    target: object = document
    for part in ref[2:].split("/"):
        target = target.get(part) if isinstance(target, dict) else None
    return target if isinstance(target, dict) else {}


def _takes_one_message(
    document: Mapping[str, Any], operation: Mapping[str, Any]
) -> bool:
    """Whether the JSON body requires exactly one field, and that field is free text."""
    body = _resolve(document, operation.get("requestBody"))
    content = body.get("content")
    media = content.get("application/json") if isinstance(content, dict) else None
    if not isinstance(media, dict):
        return False
    schema = _resolve(document, media.get("schema"))
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return False
    if len(required) != 1:
        return False
    field = _resolve(document, properties.get(required[0]))
    return (
        field.get("type") == "string" and not {"enum", "format", "const"} & field.keys()
    )


def _pattern(method: str, path: str) -> str:
    """The `METHOD /glob` for an operation. A `{name}` path parameter becomes `*`."""
    return f"{method} {_PARAMETER.sub('*', path)}"


def suggest_submissions(document: Mapping[str, Any]) -> list[str]:
    """The writes whose JSON body takes one required free-text field, as binding patterns."""
    return list(
        dict.fromkeys(
            _pattern(method, path)
            for method, path, operation in _operations(document)
            if method.lower() in _WRITE_METHODS
            and _takes_one_message(document, operation)
        )
    )


def submission_warnings(
    patterns: list[str], document: Mapping[str, Any]
) -> list[ConnectionFieldError]:
    """One warning for each `submissions` pattern that matches no call in the document."""
    calls = [
        (method, _PARAMETER.sub("_", path)) for method, path, _ in _operations(document)
    ]
    return [
        ConnectionFieldError(
            loc=["submissions", index],
            msg=f"{pattern} matches no call in the OpenAPI document.",
        )
        for index, pattern in enumerate(patterns)
        if not any(call_matches(pattern, method, path) for method, path in calls)
    ]


# ── the Interview and the export ──────────────────────────────────────────


def set_connection(
    state: InterviewState, connection: TargetConnection | None
) -> InterviewState:
    """Return a copy of the state with the connection set, or removed with `None`."""
    context = state.context.model_copy(update={"connection": connection})
    return state.model_copy(update={"context": context}, deep=True)


def connected_specification(
    specification: Specification, connection: TargetConnection | None
) -> Specification:
    """The Specification to export: with a connection, it names the generic runner and the binding.

    With no connection, the Specification is returned unchanged, so a spec-only export keeps
    the default runner.
    """
    if connection is None:
        return specification
    document = specification.model_copy(deep=True)
    document.runner_factory_ref = RUNNER_FACTORY_REFS[connection.transport]
    document.target_binding = TARGET_BINDING_FILE
    return document


def binding_yaml(connection: TargetConnection) -> str:
    """The binding file, with a comment that lists the variables to set before a run."""
    binding = connection.binding
    required = required_variables(binding)
    optional = optional_variables(binding)
    lines = [
        "# A target binding written by the METIS Wizard. It names environment variables",
        "# and holds no secret value. Set each variable in `.env` or in the environment",
        "# before `metis engine run`.",
    ]
    if required:
        lines.append(f"# Required: {', '.join(required)}")
    if optional:
        lines.append(
            f"# Optional (a header is left out when it is not set): {', '.join(optional)}"
        )
    lines.append(
        "# The Wizard reached the target with this binding."
        if connection.status is ConnectionStatus.CHECKED
        else "# The Wizard did not check this binding against the target."
    )
    body = yaml.safe_dump(
        binding.model_dump(mode="json", exclude_defaults=True),
        sort_keys=False,
        allow_unicode=True,
        width=88,
    )
    return "\n".join(lines) + "\n" + body


__all__ = [
    "RUNNER_FACTORY_REFS",
    "TARGET_BINDING_FILE",
    "binding_yaml",
    "check_connection",
    "connected_specification",
    "field_errors",
    "live_probes",
    "optional_variables",
    "required_variables",
    "set_connection",
    "submission_warnings",
    "suggest_submissions",
    "validate_binding",
]
