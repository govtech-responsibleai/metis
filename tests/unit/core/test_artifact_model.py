"""The Artifact domain model and resolve_artifact_path (#328, #351)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from metis.core import Artifact, resolve_artifact_path


def test_artifact_defaults() -> None:
    art = Artifact(name="report.csv", state="unavailable")
    assert art.source == "target"
    assert art.path is None
    assert art.at_simulated_turn is None
    assert art.content_description is None
    assert art.state_description is None
    assert art.digest is None
    assert art.hash_algorithm is None
    assert art.id  # auto-generated


def test_artifact_round_trips() -> None:
    art = Artifact(
        name="report.csv",
        source="target",
        state="received",
        path="runs/s1-p1-1/artifacts/report.csv",
        at_simulated_turn=2,
        content_description="Q3 sales export",
        digest="a" * 64,
        hash_algorithm="SHA256",
    )
    restored = Artifact.model_validate(art.model_dump())
    assert restored == art


def test_state_is_required() -> None:
    with pytest.raises(ValidationError):
        Artifact(name="report.csv")  # type: ignore[call-arg]


def test_received_without_a_path_is_rejected() -> None:
    """The one-directional invariant: state="received" implies a path."""
    with pytest.raises(ValidationError, match="state='received'"):
        Artifact(name="report.csv", state="received", path=None)


def test_unfetched_and_unavailable_allow_no_path() -> None:
    # The reverse never holds: a path-less artifact may be unfetched (a
    # retryable download failure) or unavailable (nothing to retry) — the
    # validator only forbids received+no-path, never the other way round.
    Artifact(name="report.csv", state="unfetched", external_id="f-9")
    Artifact(name="report.csv", state="unavailable")


def test_media_type_guessed_from_name() -> None:
    art = Artifact(name="report.csv", path="report.csv", state="received")
    assert art.media_type == "text/csv"


def test_media_type_falls_back_to_path() -> None:
    art = Artifact(name="report", path="runs/x/artifacts/report.csv", state="received")
    assert art.media_type == "text/csv"


def test_media_type_none_when_unresolvable() -> None:
    # Both name and path lack a recognizable extension, so the guess fails
    # even though the artifact was genuinely received.
    art = Artifact(name="report", path="report", state="received")
    assert art.media_type is None


def test_media_type_none_when_state_is_not_received() -> None:
    # "report.csv" has a perfectly guessable extension; the gate on `state`
    # is what returns None here, not a failed guess.
    art = Artifact(name="report.csv", state="unavailable")
    assert art.media_type is None


def test_resolve_artifact_path_joins_relative_path(tmp_path: Path) -> None:
    resolved = resolve_artifact_path(tmp_path, "runs/s1-p1-1/artifacts/report.csv")
    assert resolved == tmp_path / "runs/s1-p1-1/artifacts/report.csv"


def test_resolve_artifact_path_none_when_path_falsy(tmp_path: Path) -> None:
    assert resolve_artifact_path(tmp_path, None) is None
    assert resolve_artifact_path(tmp_path, "") is None


class TestExternalId:
    def test_defaults_to_none(self) -> None:
        """A runner with no target-side identifier leaves it unset."""
        assert Artifact(name="chart.vl.json", state="unavailable").external_id is None

    def test_round_trips_through_serialization(self) -> None:
        """record.json must carry it, or a completed run cannot be re-checked."""
        artifact = Artifact(
            name="chart.vl.json", external_id="73da06dac970f8a9", state="unavailable"
        )
        assert Artifact.model_validate(artifact.model_dump()).external_id == (
            "73da06dac970f8a9"
        )

    def test_is_independent_of_the_metis_id(self) -> None:
        """The uuid4 identifies the record; external_id identifies the file."""
        artifact = Artifact(
            name="chart.vl.json", external_id="73da06dac970f8a9", state="unavailable"
        )
        assert artifact.id != artifact.external_id

    def test_existing_records_without_the_field_still_load(self) -> None:
        """Additive and optional: no schema_version bump, old records keep working.

        ``state`` itself is NOT covered by this guarantee — it's the new
        required field #351 adds, with no legacy exemption. No production
        code re-validates a genuinely pre-#351 ``record.json`` into this
        model, so this fixture represents a record from AFTER #351 that
        simply predates ``external_id`` (added earlier, and still optional).
        """
        legacy = {
            "id": "abc",
            "name": "report.txt",
            "source": "target",
            "path": None,
            "state": "unavailable",
        }
        assert Artifact.model_validate(legacy).external_id is None
