"""Loads a target binding from the experiment's ``inputs/`` and reads its secrets.

Core's ``TargetBinding`` checks the file's shape. This module adds what needs the
environment: ``${NAME}`` references in ``spec_url`` (or a browser binding's ``start_url``)
are expanded, a relative ``spec_url`` becomes a file beside the binding, and the
credentials the binding names are read. A
value read from the environment never appears in an error, a repr or a log line; errors
name the variable instead.

The binding must sit inside the input folder, because only that folder is copied into
the experiment, and ``--resume`` reads the copy.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import SecretStr, ValidationError

from metis.core.logging import get_logger
from metis.core.target_binding import TargetBinding

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    _Fail = Callable[[str], "TargetBindingError"]

logger = get_logger()

_ENV = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class TargetBindingError(ValueError):
    """A target binding that cannot be used; raised before any trial runs."""


@dataclass(frozen=True)
class LoadedBinding:
    """A binding as written, with what the engine read from the environment for it."""

    path: Path
    """The binding file, resolved."""
    binding: TargetBinding
    """As written: holds ``${NAME}`` references and no environment value."""
    spec_url: str | None = field(repr=False)
    """``spec_url`` expanded: an http(s) URL, or a ``file:`` URI inside the input folder.
    ``None`` for a browser binding."""
    secrets: Mapping[str, SecretStr]
    """Environment variable name to value, for the variables that are set."""
    start_url: str | None = field(default=None, repr=False)
    """A browser binding's ``start_url`` expanded to an http(s) URL; ``None`` for http."""

    def secret(self, env: str) -> SecretStr | None:
        """The value of ``env``, or ``None`` when it was not set."""
        return self.secrets.get(env)


def _env(name: str) -> str | None:
    """The variable's value; empty counts as unset."""
    return os.environ.get(name) or None


def load_target_binding(
    inputs_dir: Path, relative: str, transport: Literal["http", "browser"] = "http"
) -> LoadedBinding:
    """Load the binding at ``relative`` (relative to ``specification.yaml``).

    :param inputs_dir: The experiment's ``inputs/`` folder.
    :param transport: The transport the caller's runner speaks; any other is refused.
    :raises TargetBindingError: Whatever makes the binding unusable. The message
        starts with ``relative`` as written.
    """

    def fail(message: str) -> TargetBindingError:
        return TargetBindingError(f"{relative}: {message}")

    root = inputs_dir.resolve()
    path = (inputs_dir / relative).resolve()
    if not path.is_relative_to(root):
        raise fail(
            "the target binding must be inside the input folder; move it there and "
            "name it relative to specification.yaml"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise fail("target binding file not found") from None
    except UnicodeDecodeError:
        raise fail("target binding file is not valid UTF-8") from None
    except OSError:
        raise fail("target binding file cannot be read") from None

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise fail(f"not valid YAML{where}") from None
    if not isinstance(data, dict):
        raise fail("a target binding must be a mapping")
    try:
        # before expansion, so an error can only hold what the user wrote
        binding = TargetBinding.model_validate(data)
    except ValidationError as exc:
        raise fail(str(exc)) from None

    if binding.transport != transport:
        raise fail(
            f"this runner needs a {transport} binding, but the binding's transport "
            f"is {binding.transport}"
        )
    spec_url = start_url = None
    if binding.spec_url is not None:
        spec_url = _resolve_url("spec_url", binding.spec_url, path.parent, root, fail)
    if binding.start_url is not None:
        start_url = _resolve_url("start_url", binding.start_url, None, root, fail)
    return LoadedBinding(
        path=path,
        binding=binding,
        spec_url=spec_url,
        secrets=_read_secrets(binding, fail),
        start_url=start_url,
    )


def _resolve_url(
    name: str, written: str, folder: Path | None, root: Path, fail: _Fail
) -> str:
    """Expand ``${NAME}`` in ``written`` and make it absolute.

    :param name: The binding field, for messages.
    :param folder: Where a relative file path is read from; ``None`` allows http(s) only.
    """
    if "${" in _ENV.sub("", written):
        raise fail(f'{name} has a "${{" that is not a ${{NAME}} reference')

    def expand(match: re.Match[str]) -> str:
        value = _env(match.group(1))
        if value is None:
            raise fail(
                f"{name} needs the environment variable {match.group(1)}, "
                "which is not set"
            )
        return value

    expanded = _ENV.sub(expand, written)
    try:
        return _absolute(name, expanded, written, folder, root, fail)
    except TargetBindingError:
        raise
    except (ValueError, OSError):
        # urlsplit and the path calls quote the value they reject, which may be secret
        raise fail(
            f"{name} {written!r}, once expanded, is not a usable URL or path"
        ) from None


def _absolute(
    name: str,
    expanded: str,
    written: str,
    folder: Path | None,
    root: Path,
    fail: _Fail,
) -> str:
    """``expanded`` as an http(s) URL or a ``file:`` URI; messages quote ``written`` only."""
    what = (
        "an http(s) URL"
        if folder is None
        else "an http(s) URL or a file path relative to the binding"
    )
    scheme = urlsplit(expanded).scheme.lower()
    if scheme in ("http", "https"):
        return expanded
    if scheme:
        # name the scheme only when the user wrote it, not when a variable supplied it
        shown = urlsplit(written).scheme.lower() == scheme
        raise fail(
            f"{name} must be {what}, "
            + (
                f'not "{scheme}:"'
                if shown
                else f"and the expanded {name} has an unsupported scheme"
            )
        )
    if folder is None:
        raise fail(f"{name} must be {what}")
    local = (folder / expanded).resolve()
    if not local.is_relative_to(root):
        raise fail(f"{name} {written!r} must name a file inside the input folder")
    if not local.is_file():
        raise fail(f"{name} {written!r} names a file that does not exist")
    return local.as_uri()


def _read_secrets(binding: TargetBinding, fail: _Fail) -> dict[str, SecretStr]:
    """Read the credential and each login secret (required) and each secret header's value (optional)."""
    secrets: dict[str, SecretStr] = {}
    if binding.login is not None:
        for env in binding.login.secrets:
            value = _env(env)
            if value is None:
                raise fail(f"login.secrets names {env}, which is not set")
            secrets[env] = SecretStr(value)
    if binding.auth is not None:
        value = _env(binding.auth.secret_env)
        if value is None:
            raise fail(
                f"auth.secret_env names {binding.auth.secret_env}, which is not set"
            )
        secrets[binding.auth.secret_env] = SecretStr(value)
    for header in binding.secret_headers:
        value = _env(header.env)
        if value is None:
            logger.warning(
                "[binding] secret header %s is left out: %s is not set",
                header.header,
                header.env,
            )
            continue
        secrets[header.env] = SecretStr(value)
    return secrets
