"""The trial the seam builds, and fixture facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from metis.core.trials import TrialConfig
from metis.engine.simulation import trial as seam
from metis.engine.simulation.artifacts import file_facts
from metis.engine.simulation.llm_calls import LLMCallLog
from metis.engine.simulation.orchestrator import Orchestrator
from metis.engine.simulation.trial import resolve_fixture_descriptions
from metis.engine.simulation.types import Persona, Scenario

if TYPE_CHECKING:
    from pathlib import Path


def _kwargs(tmp_path: Path) -> dict[str, Any]:
    return {
        "runner": MagicMock(),
        "persona": Persona(id="p1", name="p1", description="d"),
        "scenario": Scenario(id="s1", description="g", persona_refs=["p1"]),
        "trial_config": TrialConfig(persona="p1", scenario="s1"),
        "run_dir": tmp_path / "t1",
        "experiment_root": tmp_path,
        "fixture_artifacts": [],
        "trial_index": 1,
        "state": None,
        "tui_ctx": None,
        "shutdown_event": None,
    }


def test_a_factory_gets_a_trial_built_by_the_orchestrator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    trial = seam.create_trial(**_kwargs(tmp_path))

    assert isinstance(trial, Orchestrator)


@pytest.mark.asyncio
async def test_fixture_descriptions_are_file_facts_with_no_llm_call(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "q3.csv").write_text("a,b\n1,2\n3,4\n")
    (fixtures / "notes.md").write_text("hello")

    described = await resolve_fixture_descriptions(
        ["q3.csv", "notes.md", "q3.csv", "missing.txt"], fixtures, tmp_path, {}
    )

    assert described == {
        "q3.csv": file_facts(fixtures / "q3.csv", "q3.csv"),
        "notes.md": file_facts(fixtures / "notes.md", "notes.md"),
    }
    assert "2 data rows, 2 columns; header: a,b" in described["q3.csv"]
    assert not LLMCallLog.for_experiment(tmp_path).path.exists()


@pytest.mark.asyncio
async def test_an_author_description_wins_over_facts(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "q3.csv").write_text("a\n1\n")

    described = await resolve_fixture_descriptions(
        ["q3.csv"], fixtures, tmp_path, {"q3.csv": "Quarterly sales, written by hand"}
    )

    assert described == {"q3.csv": "Quarterly sales, written by hand"}
