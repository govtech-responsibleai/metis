"""Artifact persistence — copies artifacts to registry and writes manifest."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from metis.core import resolve_artifact_path
from metis.core.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.trials import TrialRecord

_TYPE_MAP = {
    "pdf": "report",
    "html": "report",
    "png": "chart",
    "jpg": "chart",
    "jpeg": "chart",
    "svg": "chart",
    "pptx": "slide_deck",
    "ppt": "slide_deck",
    "xlsx": "spreadsheet",
    "xls": "spreadsheet",
    "csv": "data",
    "json": "data",
}

logger = get_logger()


def quarantine_stale_artifacts(
    run_dir: Path, *, now: datetime | None = None
) -> Path | None:
    """Move a populated ``run_dir/artifacts/`` aside so an attempt starts clean.

    A run directory belongs to one scenario × persona × trial, but every
    *attempt* at that run writes its downloads into the same ``artifacts/``
    folder, and nothing cleared it between attempts (issue #346). The API
    runner's collision handling then stored attempt 2's ``report.pdf`` as
    ``report-2.pdf`` — a name implying a duplicate when it is the only good
    copy — while the browser runner's ``save_as`` overwrote attempt 1's file
    in place. Either way the surviving ``record.json`` describes one attempt
    and the folder holds the debris of several.

    The trigger is the folder's contents rather than the attempt counter,
    because ``--resume`` re-runs a ``system_error`` run in a **new process**
    whose counter starts at 1 again while the folder still holds the previous
    process's downloads. An interrupted run is the same case with no
    ``record.json`` at all, so its files are referenced by nothing.

    The destination is ``artifacts-superseded-<UTC timestamp>``, named for the
    moment of the move rather than for an attempt number: an attempt that
    downloaded nothing leaves an empty folder, which is skipped, so a
    quarantine counter is not an attempt counter and ``failed-attempt-1``
    would be free to name attempt 2's files. The ``artifacts-`` prefix says
    which directory was superseded and sorts the folder next to it.

    :param run_dir: The run folder (``outputs/trials/<scenario>-<persona>-<trial>/``).
    :param now: Timestamp for the destination name. Defaults to the current
        UTC time; injected by tests for a deterministic name.
    :returns: The directory the artifacts were moved to, or ``None`` when
        there was nothing to move — no ``artifacts/`` yet, or an empty one.
        Never deletes anything.
    """
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir() or not any(artifacts_dir.iterdir()):
        return None

    stamp = (now or datetime.now(tz=UTC)).strftime("%Y%m%dT%H%M%SZ")
    stem = f"artifacts-superseded-{stamp}"
    dest = run_dir / stem
    suffix = 2
    while dest.exists():
        dest = run_dir / f"{stem}-{suffix}"
        suffix += 1

    artifacts_dir.rename(dest)
    logger.info(
        "[experiment] Moved a previous attempt's artifacts aside",
        run_dir=str(run_dir),
        moved_to=dest.name,
    )
    return dest


def infer_artifact_type(filename: str) -> str:
    """Infer the artifact type from a filename based on its extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _TYPE_MAP.get(ext, "unknown")


def _save_artifacts(record: TrialRecord, run_dir: Path, experiment_root: Path) -> dict:
    """Write an artifact manifest for a completed simulation run.

    Artifacts are already on disk at their collected paths (written live during
    simulation). This function records them in a manifest file and returns the
    manifest dict.

    :param record: The completed run record.
    :param run_dir: The run folder (``outputs/trials/<task>-<persona>-<trial>/``).
    :param experiment_root: The experiment directory each artifact's ``path`` is
        relative to.
    :returns: The manifest dict (also written to ``run_dir/artifacts/run-manifest.json``).
    """
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    manifest_artifacts = []
    for artifact in record.artifacts:
        local = resolve_artifact_path(experiment_root, artifact.path)
        manifest_artifacts.append(
            {
                "filename": artifact.name,
                "type": infer_artifact_type(artifact.name),
                "source": artifact.source,
                "state": artifact.state,
                "external_id": artifact.external_id,
                "at_simulated_turn": artifact.at_simulated_turn,
                "path": str(local) if local else "",
            }
        )

    manifest = {
        "session_id": record.target_session_id or "",
        "persona": record.config.persona,
        "scenario": record.config.scenario,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "stop_reason": record.outcome.stop_reason,
        "artifacts": manifest_artifacts,
    }

    manifest_path = artifacts_dir / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return manifest
