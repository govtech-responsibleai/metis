"""Build Artifact records for a scenario's staged fixtures (inbound files, #321)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.core import Artifact
from metis.core.logging import get_logger

from ._hashing import sha256_file

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()


def build_fixture_artifacts(
    fixtures: list[str],
    fixtures_dir: Path,
    experiment_root: Path,
    content_descriptions: dict[str, str] | None = None,
) -> list[Artifact]:
    """One ``source="fixture"`` Artifact per staged fixture that exists on disk.

    Resolves each name under ``fixtures_dir`` (rejecting path escapes and the
    directory itself), sets a relative ``path``, and computes a SHA-256 digest
    from the bytes in hand. ``at_simulated_turn`` stays ``None``. ``content_description``
    is set from the optional ``content_descriptions`` map when the name is
    present, else ``None``.
    """
    fixtures_root = fixtures_dir.resolve()
    experiment_root = experiment_root.resolve()
    artifacts: list[Artifact] = []
    for name in fixtures:
        path = (fixtures_dir / name).resolve()
        if (
            path == fixtures_root
            or not path.is_relative_to(fixtures_root)
            or not path.is_file()
        ):
            logger.warning(
                "[fixtures] fixture %r not found under %s; not recorded",
                name,
                fixtures_root,
            )
            continue
        try:
            digest: str | None = sha256_file(path)
        except OSError as exc:
            logger.warning("[fixtures] digest failed for %r: %s", name, exc)
            digest = None
        artifacts.append(
            Artifact(
                name=name,
                source="fixture",
                state="received",
                path=path.relative_to(experiment_root).as_posix(),
                digest=digest,
                hash_algorithm="SHA256" if digest else None,
                content_description=(content_descriptions or {}).get(name),
            )
        )
    return artifacts
