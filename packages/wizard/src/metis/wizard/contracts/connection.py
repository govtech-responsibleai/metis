"""The target connection: how METIS reaches the target, kept apart from the Target Profile.

The Profile states what METIS evaluates. The connection states how the engine reaches the
target: one `TargetBinding` for the generic HTTP or browser runner. A binding names
environment variables and never holds a secret value, so the connection can travel in the
client-held Interview state. Prompts and the model gateway never read it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializationInfo,
    field_serializer,
    model_validator,
)

from metis.core.target_binding import TargetBinding

# a pasted secret can sit in a rejected value, so these models hide input values in their
# error messages. Pydantic applies the setting of the outermost model that is validated, so
# each model that can carry a binding sets it.
_REDACTED = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ConnectionTransport(StrEnum):
    """How the engine reaches the target."""

    HTTP = "http"
    BROWSER = "browser"


class ConnectionStatus(StrEnum):
    """Whether the Wizard reached the target with this binding."""

    CHECKED = "checked"
    UNCHECKED = "unchecked"


class TargetConnection(BaseModel):
    """A valid target binding and the result of the last connection check."""

    model_config = _REDACTED

    transport: ConnectionTransport
    binding: TargetBinding
    status: ConnectionStatus = ConnectionStatus.UNCHECKED

    @model_validator(mode="after")
    def _transport_matches_binding(self) -> TargetConnection:
        if self.binding.transport != self.transport.value:
            raise ValueError("transport must match binding.transport")
        return self

    # A full dump of a browser binding writes the HTTP-only defaults, which TargetBinding then
    # rejects as fields set for the wrong transport. Leave defaults out so the binding loads
    # again from JSON and from the YAML file. The return type stays unannotated so the
    # serialization schema stays the TargetBinding schema in the generated API contract.
    @field_serializer("binding")
    def _write_binding(self, binding: TargetBinding, info: SerializationInfo):  # noqa: ANN202
        return binding.model_dump(mode=info.mode, exclude_defaults=True)


class ConnectionFieldError(BaseModel):
    """One binding field that failed validation. It never holds the rejected value."""

    loc: list[str | int]
    msg: str


class ConnectionProbe(BaseModel):
    """One live check: a named environment variable or a request to the target."""

    name: str
    ok: bool
    message: str


class ConnectionCheckRequest(BaseModel):
    """Binding values to check.

    The values are a plain mapping, so a binding that does not validate comes back as field
    errors in a normal result and not as a request failure.
    """

    model_config = _REDACTED

    binding: dict[str, Any]


class ConnectionCheckResult(BaseModel):
    """The result of a connection check.

    `binding` is the validated binding, or `None` when `errors` is not empty. `live` is true
    when the Wizard also checked the environment and reached the target; `probes` holds those
    results. `status` is `checked` only when the live checks ran and all passed.

    When the check read an OpenAPI document, `suggested_submissions` lists the calls that look
    like they send the user's message, and `warnings` names each `submissions` pattern that
    matches no call in the document. A warning does not make the binding invalid, and the
    Wizard never puts a suggestion into the binding. The user chooses.
    """

    binding: TargetBinding | None = None
    errors: list[ConnectionFieldError] = Field(default_factory=list)
    live: bool = False
    probes: list[ConnectionProbe] = Field(default_factory=list)
    status: ConnectionStatus = ConnectionStatus.UNCHECKED
    suggested_submissions: list[str] = Field(default_factory=list)
    warnings: list[ConnectionFieldError] = Field(default_factory=list)

    @field_serializer("binding")
    def _write_binding(self, binding: TargetBinding | None, info: SerializationInfo):  # noqa: ANN202
        if binding is None:
            return None
        return binding.model_dump(mode=info.mode, exclude_defaults=True)

    @property
    def valid(self) -> bool:
        return self.binding is not None

    def connection(self) -> TargetConnection | None:
        """The connection to keep, or `None` when the binding is not valid."""
        if self.binding is None:
            return None
        return TargetConnection(
            transport=ConnectionTransport(self.binding.transport),
            binding=self.binding,
            status=self.status,
        )


__all__ = [
    "ConnectionCheckRequest",
    "ConnectionCheckResult",
    "ConnectionFieldError",
    "ConnectionProbe",
    "ConnectionStatus",
    "ConnectionTransport",
    "TargetConnection",
]
