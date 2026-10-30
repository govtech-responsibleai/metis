"""The "run one trial" seam between the retry loop and a trial."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from metis.core.experiment import ExperimentDefaults
from metis.core.trials import TrialConfig
from metis.engine.simulation import experiment as experiment_module
from metis.engine.simulation import trial as seam
from metis.engine.simulation.experiment import (
    TrialPlanItem,
    _execute_experiment_async,
    _worker,
)
from metis.engine.simulation.llm_calls import LLMCallLog
from metis.engine.simulation.model_settings import user_agent_settings
from metis.engine.simulation.trial import create_trial
from metis.engine.simulation.types import Persona, Scenario


class _Factory:
    """Factory that hands out mock runners and counts how many it made."""

    def __init__(self) -> None:
        self.created = 0

    async def start(self) -> None:
        pass

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> Any:
        self.created += 1
        return AsyncMock()

    async def close(self) -> None:
        pass


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        id="test-scenario",
        description="A simple test scenario",
        persona_refs=["tester"],
        num_trials=1,
        max_turns=1,
        grader_refs=[],
    )


@pytest.fixture
def persona() -> Persona:
    return Persona(id="tester", name="tester", description="A test persona")


def _trial_kwargs(
    persona: Persona, scenario: Scenario, tmp_path: Path
) -> dict[str, Any]:
    return {
        "runner": "runner",
        "persona": persona,
        "scenario": scenario,
        "trial_config": TrialConfig(persona="tester", scenario="test-scenario"),
        "run_dir": tmp_path,
        "experiment_root": tmp_path,
        "fixture_artifacts": [],
        "trial_index": 1,
        "state": None,
        "tui_ctx": None,
        "shutdown_event": None,
    }


async def _run_worker(
    factory: _Factory,
    persona: Persona,
    scenario: Scenario,
    tmp_path: Path,
    *,
    trial_max_retries: int,
) -> list[Any]:
    return await _worker(
        worker_id=0,
        runner_factory=factory,
        worker_trials=[TrialPlanItem(scenario, persona, 1)],
        experiment_root=tmp_path,
        fixtures_dir=tmp_path / "fixtures",
        fixture_content_descriptions={},
        console_lock=asyncio.Lock(),
        started_scenarios=set(),
        trial_max_retries=trial_max_retries,
        trial_retry_delay_seconds=0,
    )


def test_create_trial_builds_the_user_agent_and_the_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    built: dict[str, dict[str, Any]] = {}

    def fake_agent(**kwargs: Any) -> str:
        built["agent"] = kwargs
        return "agent"

    def fake_orchestrator(**kwargs: Any) -> str:
        built["orch"] = kwargs
        return "orch"

    monkeypatch.setattr(seam, "UserAgent", fake_agent)
    monkeypatch.setattr(seam, "Orchestrator", fake_orchestrator)

    trial = create_trial(**_trial_kwargs(persona, scenario, tmp_path))

    assert trial == "orch"
    assert built["agent"] == {
        "persona": persona,
        "scenario": scenario,
        "llm_log": LLMCallLog.for_trial(tmp_path),
        "settings": user_agent_settings(),
    }
    assert set(built["orch"]) == {
        "runner",
        "agent",
        "trial_config",
        "scenario",
        "run_dir",
        "experiment_root",
        "fixture_artifacts",
        "trial_index",
        "state",
        "tui_ctx",
        "shutdown_event",
    }
    assert built["orch"]["agent"] == "agent"
    assert built["orch"]["runner"] == "runner"


@pytest.mark.asyncio
async def test_worker_create_failure_propagates(
    persona: Persona, scenario: Scenario, tmp_path: Path
) -> None:
    factory = _Factory()
    factory.create = AsyncMock(side_effect=RuntimeError("no browser"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="no browser"):
        await _run_worker(factory, persona, scenario, tmp_path, trial_max_retries=2)

    assert factory.create.await_count == 1


@pytest.mark.asyncio
async def test_trial_construction_failure_retries_with_empty_record(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    def boom(**_kwargs: Any) -> None:
        raise RuntimeError("bad persona")

    monkeypatch.setattr(seam, "UserAgent", boom)
    factory = _Factory()

    [record] = await _run_worker(
        factory, persona, scenario, tmp_path, trial_max_retries=1
    )

    assert factory.created == 2
    assert record.outcome.stop_reason == "system_error"
    assert record.outcome.simulated_turns_completed == 0
    assert record.attempt_number == 2
    assert record.max_allowed_attempts == 2
    assert [f.failure_type for f in record.prior_failures] == [
        "RuntimeError",
        "RuntimeError",
    ]
    assert record.prior_failures[0].error_message == "bad persona"


@pytest.mark.asyncio
async def test_experiment_resolves_descriptions_once_before_workers_start(
    monkeypatch: pytest.MonkeyPatch,
    persona: Persona,
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    resolver = AsyncMock(return_value={"a.csv": "described"})

    async def counting(*args: Any, **kwargs: Any) -> dict[str, str]:
        events.append("resolve")
        return await resolver(*args, **kwargs)

    async def fake_worker(**kwargs: Any) -> list[Any]:
        events.append("worker")
        assert kwargs["fixture_content_descriptions"] == {"a.csv": "described"}
        return []

    monkeypatch.setattr(experiment_module, "resolve_fixture_descriptions", counting)
    monkeypatch.setattr(experiment_module, "_worker", fake_worker)
    specification = SimpleNamespace(
        id="test-experiment",
        scenarios=[scenario],
        tasks=[],
        fixture_content_descriptions={},
        experiment=SimpleNamespace(defaults=ExperimentDefaults()),
    )
    plan = [TrialPlanItem(scenario, persona, i) for i in (1, 2, 3)]

    await _execute_experiment_async(
        _Factory(),
        specification,
        {persona.id: persona},
        tmp_path / "fixtures",
        plan,
        output_dir=tmp_path,
        concurrency=3,
    )

    assert events == ["resolve", "worker", "worker", "worker"]
    resolver.assert_awaited_once()
