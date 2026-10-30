"""A target binding: what the generic HTTP runner needs to know about one app.

A user writes this file by hand instead of a Python runner. Core validates its shape
only. The engine loads it and expands ``${NAME}`` references from the environment, so
values such as ``spec_url`` are kept here as written. Secrets never appear in the file:
it names environment variables, which the engine reads when it loads the binding and uses
only when sending.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

_TARGET_BINDING_VERSION = 1

_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_SECRET_PLACEHOLDER = re.compile(r"\{\{secret:([^{}]*)\}\}")

EnvName = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]*$")]
"""The name of an environment variable, never its value."""

CallPattern = Annotated[
    str,
    StringConstraints(
        pattern=r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|\*) /[^\s{}?#]*$"
    ),
]
"""``METHOD /path/glob``: ``*`` matches within a path segment, ``**`` across segments.
OpenAPI's ``{name}`` parameters, queries and fragments are rejected, since a pattern
holding them would never match a request path; write ``*`` for a parameter."""


def call_matches(pattern: str, method: str, path: str) -> bool:
    """Whether a ``CallPattern`` covers a call: ``*`` within a segment, ``**`` across."""
    verb, _, glob = pattern.partition(" ")
    regex = "".join(
        ".*" if part == "**" else "[^/]*" if part == "*" else re.escape(part)
        for part in re.split(r"(\*\*|\*)", glob)
    )
    return verb in ("*", method) and re.fullmatch(regex, path) is not None


_Path = Annotated[str, StringConstraints(pattern=r"^/[^\s{}?#]*$")]


class _BindingModel(BaseModel):
    # error messages never repeat the rejected value, which may be a pasted secret. This
    # holds only when TargetBinding is validated directly, not as a field of another model,
    # and only for str(error): never log error.errors() or error.json() unredacted.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TargetIdentity(_BindingModel):
    """Which app this binding is for."""

    name: str = Field(min_length=1)
    version: str | None = None


class Auth(_BindingModel):
    """How the engine authenticates every request. The runner agent never sees it."""

    scheme: Literal["from_spec"] = Field(
        default="from_spec",
        description="Use the security scheme the API specification declares.",
    )
    secret_env: EnvName = Field(
        description="The environment variable holding the credential."
    )


class SecretHeader(_BindingModel):
    """A header the engine adds, from an environment variable, to matching requests."""

    match: CallPattern
    header: str = Field(pattern=r"^[A-Za-z0-9-]+$")
    env: EnvName = Field(description="The environment variable holding the value.")


class Limits(_BindingModel):
    """The target's rate limits, as the runner agent should pace itself."""

    submit_per_minute: int | None = Field(default=None, gt=0)
    read_per_minute: int | None = Field(default=None, gt=0)
    note: str = ""


class Advice(_BindingModel):
    """Advice for the runner agent. Code does not check these fields."""

    limits: Limits | None = None
    notes: str = ""


class Login(_BindingModel):
    """How the runner agent signs in to a web app before the first trial."""

    note: str = Field(
        min_length=1,
        description=(
            "The sign-in steps in plain words. Write `{{secret:NAME}}` where a secret "
            "is typed; the engine fills it in and logs `***`."
        ),
    )
    secrets: list[EnvName] = Field(
        default_factory=list,
        description="The environment variables holding the secrets the note types.",
    )

    @model_validator(mode="after")
    def _placeholders_are_listed(self) -> Login:
        # the engine types only the secrets it read, so a placeholder for a name that is not
        # listed would reach the page as literal text. A placeholder that is not a variable
        # name may hold a pasted secret, so the message names only valid variable names.
        for name in _SECRET_PLACEHOLDER.findall(self.note):
            if not _ENV_NAME.fullmatch(name):
                raise ValueError(
                    "login.note has a {{secret:...}} placeholder that is not an "
                    "environment variable name"
                )
            if name not in self.secrets:
                raise ValueError(
                    f"login.note uses {{{{secret:{name}}}}}, but login.secrets "
                    f"does not list {name}"
                )
        return self


_HTTP_ONLY = (
    "spec_url",
    "tls_verify",
    "auth",
    "secret_headers",
    "submissions",
    "forbidden_calls",
    "preflight_reads",
)
_BROWSER_ONLY = ("start_url", "login")


class TargetBinding(_BindingModel):
    """A hand-written binding of one app to the generic HTTP or browser runner.

    An ``http`` binding needs ``spec_url``. A ``browser`` binding needs ``start_url`` and
    may add ``login``. Each transport rejects the other's fields.
    """

    schema_version: Literal[1]
    identity: TargetIdentity
    transport: Literal["http", "browser"]
    spec_url: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Where to fetch the app's OpenAPI specification; required for `http`. "
            "`${NAME}` references are expanded from the environment by the engine."
        ),
    )
    start_url: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The page the browser opens first; required for `browser`. `${NAME}` "
            "references are expanded from the environment by the engine."
        ),
    )
    login: Login | None = None
    tls_verify: bool = True
    auth: Auth | None = None
    secret_headers: list[SecretHeader] = Field(
        default_factory=list,
        description="Headers the engine adds to matching requests; never shown to the runner agent.",
    )
    submissions: list[CallPattern] = Field(
        default_factory=list,
        description=(
            "Endpoints whose calls send the user's message. Empty means the engine's "
            "default rule: any POST, PUT or PATCH with a JSON body."
        ),
    )
    forbidden_calls: list[CallPattern] = Field(
        default_factory=list,
        description="Calls the engine refuses to send.",
    )
    preflight_reads: list[_Path] = Field(
        default_factory=list,
        description="Paths the engine reads before a trial; a failure is a warning only.",
    )
    advice: Advice = Field(default_factory=Advice)

    @model_validator(mode="after")
    def _fields_match_transport(self) -> TargetBinding:
        # messages name fields only, never values, which may be a pasted secret
        required, foreign = (
            ("spec_url", _BROWSER_ONLY)
            if self.transport == "http"
            else ("start_url", _HTTP_ONLY)
        )
        if getattr(self, required) is None:
            raise ValueError(f"a {self.transport} binding needs {required}")
        wrong = [name for name in foreign if name in self.model_fields_set]
        if wrong:
            raise ValueError(
                f"a {self.transport} binding cannot set {', '.join(wrong)}"
            )
        return self
