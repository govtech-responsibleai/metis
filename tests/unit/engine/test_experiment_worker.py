"""Tests for _worker using a mock RunnerFactory."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
from metis.engine.simulation.exceptions import ConsecutiveFailureEscalation
from metis.engine.simulation.experiment import (
    TrialPlanItem,
    _worker,
    trial_folder_name,
)
from metis.engine.simulation.runner import Runner
from metis.engine.simulation.types import (
    Observation,
    Persona,
    Promise,
    Reading,
    Scenario,
    Specification,
)


class MockRunner(Runner):
    """Runner that completes immediately with a canned response."""

    def __init__(self) -> None:
        self.setup_called = False
        self.teardown_called = False

    @property
    def session_id(self) -> str | None:
        return "sess-mock-123"

    async def setup(self, config: TrialConfig) -> None:
        self.setup_called = True

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        return Observation(
            reply="Goal achieved",
            reading=Reading(outcome="completed", why="The canned reply."),
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        pass

    async def teardown(self) -> None:
        self.teardown_called = True


class MockRunnerFactory:
    """Factory that returns MockRunners without needing Playwright."""

    def __init__(self) -> None:
        self.started = False
        self.runners_created: list[MockRunner] = []

    async def start(self) -> None:
        self.started = True

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> Runner:
        runner = MockRunner()
        self.runners_created.append(runner)
        return runner

    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def stub_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "metis.engine.simulation.trial.UserAgent", lambda **kwargs: object()
    )


@pytest.fixture
def simple_scenario() -> Scenario:
    return Scenario(
        id="test-scenario",
        description="A simple test scenario",
        persona_refs=["tester"],
        num_trials=1,
        max_turns=1,
        grader_refs=[],
    )


@pytest.fixture
def simple_persona() -> Persona:
    return Persona(id="tester", name="tester", description="A test persona")


def _make_canned_record(scenario: Scenario, persona: Persona) -> TrialRecord:
    """Create a canned TrialRecord that the mocked orchestrator returns."""
    return TrialRecord(
        config=TrialConfig(
            persona=persona.id,
            scenario=scenario.id,
            grader_refs=[],
            max_turns=1,
        ),
        target_session_id="sess-mock-123",
        outcome=TrialOutcome(
            stop_reason="goal_achieved",
            simulated_turns_completed=1,
            duration_seconds=0.1,
        ),
        artifacts=[],
    )


class TestWorkerWithMockFactory:
    @pytest.mark.asyncio
    async def test_worker_uses_factory_create(
        self, simple_scenario: Scenario, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """_worker calls runner_factory.create() and produces a TrialRecord."""
        factory = MockRunnerFactory()
        await factory.start()

        worker_trials = [TrialPlanItem(simple_scenario, simple_persona, 1)]
        console_lock = asyncio.Lock()

        canned = _make_canned_record(simple_scenario, simple_persona)

        with patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls:
            mock_orch_instance = AsyncMock()
            mock_orch_instance.execute = AsyncMock(return_value=canned)
            mock_orch_cls.return_value = mock_orch_instance

            records = await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=worker_trials,
                experiment_root=tmp_path,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=console_lock,
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=1.0,
            )

        # Factory should have been called to create a runner
        assert len(factory.runners_created) >= 1
        # Should produce exactly 1 record
        assert len(records) == 1
        assert records[0].outcome.stop_reason == "goal_achieved"

    @pytest.mark.asyncio
    async def test_worker_factory_create_receives_correct_paths(
        self, simple_scenario: Scenario, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """runner_factory.create() is called with the correct run_dir and fixtures_dir."""
        factory = MockRunnerFactory()
        await factory.start()

        fixtures_dir = tmp_path / "fixtures"
        worker_trials = [TrialPlanItem(simple_scenario, simple_persona, 1)]
        console_lock = asyncio.Lock()

        canned = _make_canned_record(simple_scenario, simple_persona)

        with patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls:
            mock_orch_instance = AsyncMock()
            mock_orch_instance.execute = AsyncMock(return_value=canned)
            mock_orch_cls.return_value = mock_orch_instance

            await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=worker_trials,
                experiment_root=tmp_path,
                fixtures_dir=fixtures_dir,
                fixture_content_descriptions={},
                console_lock=console_lock,
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=1.0,
            )

        # Verify runner was created
        assert len(factory.runners_created) == 1

        # Verify the expected run_dir path was constructed
        expected_folder = trial_folder_name(simple_scenario, simple_persona, 1)
        expected_run_dir = tmp_path / "outputs" / "trials" / expected_folder
        assert expected_run_dir.exists()


class TestNoPlaywrightImport:
    def test_experiment_module_has_no_playwright_imports(self) -> None:
        """Verify experiment.py has no playwright imports in its source."""
        import metis.engine.simulation.experiment as mod

        source = inspect.getsource(mod)
        # Should not have 'from playwright' or 'import playwright'
        assert "from playwright" not in source
        assert "import playwright" not in source

    def test_experiment_module_has_no_runner_import(self) -> None:
        """Verify experiment.py does not import a runner directly."""
        import metis.engine.simulation.experiment as mod

        source = inspect.getsource(mod)
        assert "BrowserRunner" not in source


def _partial_record(
    scenario: Scenario, persona: Persona, *, turns: int, stop_reason: str
) -> TrialRecord:
    """A TrialRecord standing in for orchestrator.partial_record() output."""
    return TrialRecord(
        config=TrialConfig(persona=persona.id, scenario=scenario.id, grader_refs=[]),
        target_session_id="sess-partial",
        outcome=TrialOutcome(
            stop_reason=stop_reason,
            simulated_turns_completed=turns,
            duration_seconds=1.0,
        ),
        artifacts=[],
    )


class TestWorkerUnexpectedCrash:
    @pytest.mark.asyncio
    async def test_crash_preserves_partial_turns(
        self, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """On an unexpected crash the recorded turn count comes from the
        orchestrator's partial state, not a zeroed-out record."""
        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=0,  # no retry: isolate preservation
            grader_refs=[],
        )
        factory = MockRunnerFactory()
        await factory.start()

        partial = _partial_record(
            scenario, simple_persona, turns=3, stop_reason="system_error"
        )

        with patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls:
            instance = AsyncMock()
            instance.execute = AsyncMock(side_effect=RuntimeError())  # message-less
            instance.partial_record = MagicMock(return_value=partial)
            mock_orch_cls.return_value = instance

            records = await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
                experiment_root=tmp_path,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=asyncio.Lock(),
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=0.0,
            )

        assert len(records) == 1
        assert records[0].outcome.stop_reason == "system_error"
        assert records[0].outcome.simulated_turns_completed == 3  # preserved, not 0
        assert len(records[0].prior_failures) == 1
        assert records[0].prior_failures[0].simulated_turns_completed == 3
        assert records[0].prior_failures[0].failure_type == "RuntimeError"

    @pytest.mark.asyncio
    async def test_crash_is_retried_then_succeeds(
        self, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """An unexpected crash on attempt 1 is retried; a successful
        attempt 2 wins, and the crash is recorded in prior_failures."""
        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=1,  # -> max_attempts == 2
            grader_refs=[],
        )
        factory = MockRunnerFactory()
        await factory.start()

        success = _make_canned_record(scenario, simple_persona)
        partial = _partial_record(
            scenario, simple_persona, turns=2, stop_reason="system_error"
        )

        with patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls:
            instance = AsyncMock()
            instance.execute = AsyncMock(side_effect=[RuntimeError(), success])
            instance.partial_record = MagicMock(return_value=partial)
            mock_orch_cls.return_value = instance

            records = await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
                experiment_root=tmp_path,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=asyncio.Lock(),
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=0.0,
            )

        assert instance.execute.await_count == 2
        assert records[0].outcome.stop_reason == "goal_achieved"
        assert records[0].attempt_number == 2
        assert records[0].max_allowed_attempts == 2
        assert len(records[0].prior_failures) == 1
        assert records[0].prior_failures[0].simulated_turns_completed == 2

    @pytest.mark.asyncio
    async def test_crash_before_orchestrator_built_falls_back_to_empty(
        self, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """If the crash happens before the Orchestrator is constructed,
        the worker still records a system_error rather than propagating."""
        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=0,
            grader_refs=[],
        )
        factory = MockRunnerFactory()
        await factory.start()

        with patch(
            "metis.engine.simulation.trial.Orchestrator",
            side_effect=RuntimeError("construction blew up"),
        ):
            records = await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
                experiment_root=tmp_path,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=asyncio.Lock(),
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=0.0,
            )

        assert len(records) == 1
        assert records[0].outcome.stop_reason == "system_error"
        assert records[0].outcome.simulated_turns_completed == 0

    @pytest.mark.asyncio
    async def test_crash_is_logged_with_traceback(
        self, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """The crash handler uses logger.exception so a traceback is captured."""
        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=0,
            grader_refs=[],
        )
        factory = MockRunnerFactory()
        await factory.start()

        partial = _partial_record(
            scenario, simple_persona, turns=1, stop_reason="system_error"
        )

        with (
            patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls,
            patch("metis.engine.simulation.experiment.logger") as mock_logger,
        ):
            instance = AsyncMock()
            instance.execute = AsyncMock(side_effect=RuntimeError())
            instance.partial_record = MagicMock(return_value=partial)
            mock_orch_cls.return_value = instance

            await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
                experiment_root=tmp_path,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=asyncio.Lock(),
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=0.0,
            )

        assert mock_logger.exception.called

    @pytest.mark.asyncio
    async def test_recoverable_exhaustion_preserves_partial_turns(
        self, simple_persona: Persona, tmp_path: Path
    ) -> None:
        """When a TrialRecoverableError exhausts the retry budget, the recorded
        turn count comes from the orchestrator's partial state, not zero."""
        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=0,  # single attempt — immediately exhausted
            grader_refs=[],
        )
        factory = MockRunnerFactory()
        await factory.start()

        partial = _partial_record(
            scenario, simple_persona, turns=3, stop_reason="system_error"
        )

        with patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls:
            instance = AsyncMock()
            instance.execute = AsyncMock(
                side_effect=ConsecutiveFailureEscalation("too many failures")
            )
            instance.partial_record = MagicMock(return_value=partial)
            mock_orch_cls.return_value = instance

            records = await _worker(
                worker_id=0,
                runner_factory=factory,
                worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
                experiment_root=tmp_path,
                fixtures_dir=tmp_path / "fixtures",
                fixture_content_descriptions={},
                console_lock=asyncio.Lock(),
                started_scenarios=set(),
                trial_max_retries=2,
                trial_retry_delay_seconds=0.0,
            )

        assert len(records) == 1
        assert records[0].outcome.stop_reason == "system_error"
        assert records[0].outcome.simulated_turns_completed == 3  # preserved, not 0
        assert len(records[0].prior_failures) == 1
        assert records[0].prior_failures[0].simulated_turns_completed == 3


class TestFixtureContentDescriptions:
    def test_experiment_accepts_fixture_content_descriptions(self) -> None:
        exp = Specification.model_validate(
            {
                "schema_version": 1,
                "fixture_content_descriptions": {"q3.csv": "Q3 sales, 200 rows."},
                "id": "e",
                "runner_factory_ref": "metis.engine.simulation.runners.http.HttpRunnerFactory",
                "personas": [{"id": "p", "description": "d", "name": "p"}],
                "scenarios": [{"id": "s", "description": "d", "name": "s"}],
                "target": {
                    "name": "Test target",
                    "users": "Test users",
                    "description": "Test target",
                },
                "tasks": [
                    {
                        "id": "TC-001",
                        "scenario_ref": "s",
                        "persona_ref": "p",
                        "fixtures": ["q3.csv"],
                        "num_trials": 1,
                        "behaviour_refs": ["EB-1"],
                    }
                ],
                "features": [
                    {
                        "id": "F-1",
                        "name": "Responses",
                        "description": "Responses",
                        "behaviours": [
                            {
                                "id": "EB-1",
                                "name": "Respond",
                                "description": "Respond correctly",
                                "measured": True,
                                "criteria": [
                                    {
                                        "id": "AC-1-1",
                                        "name": "Check 1",
                                        "description": "Given a request, when the agent responds, then the requirement is met.",
                                        "grader_fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader",
                                        "grader_args": {},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        assert exp.fixture_content_descriptions == {"q3.csv": "Q3 sales, 200 rows."}

    def test_experiment_defaults_fixture_content_descriptions_to_empty(self) -> None:
        exp = Specification.model_validate(
            {
                "schema_version": 1,
                "id": "e",
                "runner_factory_ref": "metis.engine.simulation.runners.http.HttpRunnerFactory",
                "personas": [{"id": "p", "description": "d", "name": "p"}],
                "scenarios": [{"id": "s", "description": "d", "name": "s"}],
                "target": {
                    "name": "Test target",
                    "users": "Test users",
                    "description": "Test target",
                },
                "tasks": [
                    {
                        "id": "TC-001",
                        "scenario_ref": "s",
                        "persona_ref": "p",
                        "fixtures": [],
                        "num_trials": 1,
                        "behaviour_refs": ["EB-1"],
                    }
                ],
                "features": [
                    {
                        "id": "F-1",
                        "name": "Responses",
                        "description": "Responses",
                        "behaviours": [
                            {
                                "id": "EB-1",
                                "name": "Respond",
                                "description": "Respond correctly",
                                "measured": True,
                                "criteria": [
                                    {
                                        "id": "AC-1-1",
                                        "name": "Check 1",
                                        "description": "Given a request, when the agent responds, then the requirement is met.",
                                        "grader_fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader",
                                        "grader_args": {},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        assert exp.fixture_content_descriptions == {}

    def test_scenario_rejects_duplicate_fixtures(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="duplicate fixture"):
            Scenario.model_validate(
                {
                    "id": "s",
                    "description": "d",
                    "persona_refs": ["p"],
                    "fixtures": ["q3.csv", "q3.csv"],
                }
            )

    def test_scenario_rejects_duplicate_persona_refs(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="duplicate persona_ref"):
            Scenario.model_validate(
                {
                    "id": "s1",
                    "description": "d",
                    "persona_refs": ["p1", "p1"],
                }
            )

    def test_scenario_dedupes_repeated_ref_in_error_message(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match=r"\['p1'\]"):
            Scenario.model_validate(
                {
                    "id": "s1",
                    "description": "d",
                    "persona_refs": ["p1", "p1", "p1"],
                }
            )

    def test_scenario_names_all_distinct_duplicated_refs(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match=r"\['p1', 'p2'\]"):
            Scenario.model_validate(
                {
                    "id": "s1",
                    "description": "d",
                    "persona_refs": ["p1", "p1", "p2", "p2"],
                }
            )

    def test_scenario_accepts_unique_persona_refs_reused_across_scenarios(
        self,
    ) -> None:
        exp = Specification.model_validate(
            {
                "schema_version": 1,
                "id": "e",
                "runner_factory_ref": "metis.engine.simulation.runners.http.HttpRunnerFactory",
                "personas": [
                    {"id": "p1", "description": "d", "name": "p1"},
                    {"id": "p2", "description": "d", "name": "p2"},
                ],
                "scenarios": [
                    {"id": "s1", "description": "d", "name": "s1"},
                    {"id": "s2", "description": "d", "name": "s2"},
                ],
                "target": {
                    "name": "Test target",
                    "users": "Test users",
                    "description": "Test target",
                },
                "tasks": [
                    {
                        "id": "TC-001",
                        "scenario_ref": "s1",
                        "persona_ref": "p1",
                        "fixtures": [],
                        "num_trials": 1,
                        "behaviour_refs": ["EB-1"],
                    },
                    {
                        "id": "TC-002",
                        "scenario_ref": "s1",
                        "persona_ref": "p2",
                        "fixtures": [],
                        "num_trials": 1,
                        "behaviour_refs": ["EB-1"],
                    },
                    {
                        "id": "TC-003",
                        "scenario_ref": "s2",
                        "persona_ref": "p1",
                        "fixtures": [],
                        "num_trials": 1,
                        "behaviour_refs": ["EB-2"],
                    },
                ],
                "features": [
                    {
                        "id": "F-1",
                        "name": "Responses",
                        "description": "Responses",
                        "behaviours": [
                            {
                                "id": "EB-1",
                                "name": "Respond",
                                "description": "Respond correctly",
                                "measured": True,
                                "criteria": [
                                    {
                                        "id": "AC-1-1",
                                        "name": "Check 1",
                                        "description": "Given a request, when the agent responds, then the requirement is met.",
                                        "grader_fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader",
                                        "grader_args": {},
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "id": "F-2",
                        "name": "Responses",
                        "description": "Responses",
                        "behaviours": [
                            {
                                "id": "EB-2",
                                "name": "Respond",
                                "description": "Respond correctly",
                                "measured": True,
                                "criteria": [
                                    {
                                        "id": "AC-2-1",
                                        "name": "Check 1",
                                        "description": "Given a request, when the agent responds, then the requirement is met.",
                                        "grader_fqn": "tests.unit.engine.graders_for_tests.FixedScoreGrader",
                                        "grader_args": {},
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        )
        assert [t.persona_ref for t in exp.tasks] == ["p1", "p2", "p1"]


@pytest.mark.asyncio
async def test_worker_builds_enriched_fixture_registry(tmp_path, monkeypatch):
    import metis.engine.simulation.trial as exp_mod
    from metis.core import Artifact
    from metis.core.trials import TrialConfig, TrialOutcome, TrialRecord
    from metis.engine.simulation.experiment import _worker
    from metis.engine.simulation.types import Persona, Scenario

    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "q3.csv").write_text("a,b\n1,2\n")

    captured: dict[str, list[Artifact]] = {}

    class FakeOrchestrator:
        def __init__(self, *, fixture_artifacts, **kwargs):
            captured["fixture_artifacts"] = fixture_artifacts

        async def execute(self):
            return TrialRecord(
                config=TrialConfig(persona="p", scenario="s"),
                outcome=TrialOutcome(
                    stop_reason="goal_achieved",
                    simulated_turns_completed=1,
                    duration_seconds=1.0,
                ),
            )

    monkeypatch.setattr(exp_mod, "Orchestrator", FakeOrchestrator)
    monkeypatch.setattr(exp_mod, "UserAgent", lambda **kwargs: object())

    factory = MockRunnerFactory()

    scenario = Scenario(
        id="s", description="d", persona_refs=["p"], fixtures=["q3.csv"]
    )
    persona = Persona(id="p", name="p", description="d")

    await _worker(
        worker_id=0,
        runner_factory=factory,
        worker_trials=[(scenario, persona, 1)],
        experiment_root=tmp_path,
        fixtures_dir=fixtures_dir,
        console_lock=__import__("asyncio").Lock(),
        started_scenarios=set(),
        trial_max_retries=0,
        trial_retry_delay_seconds=0.0,
        fixture_content_descriptions={"q3.csv": "Q3 sales, 200 rows."},
    )

    arts = captured["fixture_artifacts"]
    assert [a.name for a in arts] == ["q3.csv"]
    assert arts[0].source == "fixture"
    assert arts[0].content_description == "Q3 sales, 200 rows."


@pytest.mark.asyncio
async def test_worker_factory_create_receives_experiment_root(
    simple_scenario: Scenario, simple_persona: Persona, tmp_path: Path
) -> None:
    """runner_factory.create() receives the worker's experiment_root."""
    factory = MockRunnerFactory()
    await factory.start()

    worker_trials = [TrialPlanItem(simple_scenario, simple_persona, 1)]
    console_lock = asyncio.Lock()
    canned = _make_canned_record(simple_scenario, simple_persona)

    captured: dict[str, object] = {}

    class RecordingFactory(MockRunnerFactory):
        async def create(
            self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
        ) -> Runner:
            captured["experiment_root"] = experiment_root
            return await super().create(run_dir, fixtures_dir, experiment_root)

    factory = RecordingFactory()
    await factory.start()

    with patch("metis.engine.simulation.trial.Orchestrator") as mock_orch_cls:
        mock_orch_instance = AsyncMock()
        mock_orch_instance.execute = AsyncMock(return_value=canned)
        mock_orch_cls.return_value = mock_orch_instance

        await _worker(
            worker_id=0,
            runner_factory=factory,
            worker_trials=worker_trials,
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=console_lock,
            started_scenarios=set(),
            trial_max_retries=2,
            trial_retry_delay_seconds=1.0,
        )

    assert captured["experiment_root"] == tmp_path


class TestAttemptScopedArtifacts:
    """A retry must not write on top of the previous attempt's downloads (#346)."""

    @pytest.mark.asyncio
    async def test_retry_moves_the_failed_attempt_artifacts_aside(
        self, simple_persona: Persona, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import metis.engine.simulation.trial as exp_mod

        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=1,  # -> max_attempts == 2
            grader_refs=[],
        )
        seen: list[int] = []

        class FakeOrchestrator:
            """Downloads report.pdf, then fails on attempt 1 and succeeds on 2."""

            def __init__(self, *, run_dir: Path, **kwargs: object) -> None:
                self._run_dir = run_dir
                seen.append(len(seen) + 1)
                self._attempt = len(seen)

            async def execute(self) -> TrialRecord:
                artifacts = self._run_dir / "artifacts"
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / "report.pdf").write_text(f"attempt {self._attempt}")
                if self._attempt == 1:
                    raise ConsecutiveFailureEscalation("2 consecutive turn failures")
                return _make_canned_record(scenario, simple_persona)

            def partial_record(self, stop_reason: str) -> TrialRecord:
                return _partial_record(
                    scenario, simple_persona, turns=0, stop_reason=stop_reason
                )

        monkeypatch.setattr(exp_mod, "Orchestrator", FakeOrchestrator)
        monkeypatch.setattr(exp_mod, "UserAgent", lambda **kwargs: object())

        factory = MockRunnerFactory()
        await factory.start()

        records = await _worker(
            worker_id=0,
            runner_factory=factory,
            worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=2,
            trial_retry_delay_seconds=0.0,
        )

        assert records[0].attempt_number == 2
        run_dir = (
            tmp_path
            / "outputs"
            / "trials"
            / trial_folder_name(scenario, simple_persona, 1)
        )
        artifacts = run_dir / "artifacts"
        # The surviving attempt's file, under its own name.
        assert (artifacts / "report.pdf").read_text() == "attempt 2"
        assert not (artifacts / "report-2.pdf").exists()
        assert sorted(p.name for p in artifacts.iterdir()) == ["report.pdf"]
        # Attempt 1's download is kept, not deleted.
        superseded = list(run_dir.glob("artifacts-superseded-*"))
        assert len(superseded) == 1
        assert (superseded[0] / "report.pdf").read_text() == "attempt 1"

    @pytest.mark.asyncio
    async def test_resumed_run_starts_at_attempt_one_and_keeps_old_artifacts(
        self, simple_persona: Persona, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two successive _worker calls on one experiment_root == a --resume.

        Pins the documented semantics: the attempt counter is per-process, so a
        resumed run starts at attempt 1 with an empty prior_failures list even
        though an earlier process already spent attempts on it. The previous
        process's downloads are moved aside rather than written over.
        """
        import metis.engine.simulation.trial as exp_mod

        scenario = Scenario(
            id="test-scenario",
            description="s",
            persona_refs=["tester"],
            num_trials=1,
            max_turns=5,
            max_trial_retries=0,  # one attempt per process
            grader_refs=[],
        )
        label = ["first process"]
        should_fail = [True]

        class FakeOrchestrator:
            def __init__(self, *, run_dir: Path, **kwargs: object) -> None:
                self._run_dir = run_dir

            async def execute(self) -> TrialRecord:
                artifacts = self._run_dir / "artifacts"
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / "report.pdf").write_text(label[0])
                if should_fail[0]:
                    raise ConsecutiveFailureEscalation("2 consecutive turn failures")
                return _make_canned_record(scenario, simple_persona)

            def partial_record(self, stop_reason: str) -> TrialRecord:
                return _partial_record(
                    scenario, simple_persona, turns=0, stop_reason=stop_reason
                )

        monkeypatch.setattr(exp_mod, "Orchestrator", FakeOrchestrator)
        monkeypatch.setattr(exp_mod, "UserAgent", lambda **kwargs: object())

        factory = MockRunnerFactory()
        await factory.start()

        first = await _worker(
            worker_id=0,
            runner_factory=factory,
            worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=2,
            trial_retry_delay_seconds=0.0,
        )
        assert first[0].outcome.stop_reason == "system_error"

        label[0] = "second process"
        should_fail[0] = False
        # Same experiment_root, so the same run_dir — this is what --resume does.
        second = await _worker(
            worker_id=0,
            runner_factory=factory,
            worker_trials=[TrialPlanItem(scenario, simple_persona, 1)],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=2,
            trial_retry_delay_seconds=0.0,
        )

        assert second[0].outcome.stop_reason == "goal_achieved"
        assert second[0].attempt_number == 1  # per-process, not a lifetime total
        assert second[0].prior_failures == []

        run_dir = (
            tmp_path
            / "outputs"
            / "trials"
            / trial_folder_name(scenario, simple_persona, 1)
        )
        assert (run_dir / "artifacts" / "report.pdf").read_text() == "second process"
        superseded = list(run_dir.glob("artifacts-superseded-*"))
        assert len(superseded) == 1
        assert (superseded[0] / "report.pdf").read_text() == "first process"


@pytest.mark.asyncio
async def test_worker_tracks_each_task_in_records_and_progress(tmp_path: Path) -> None:
    from metis.engine.tui.state import (
        SimulationScenarioState,
        SimulationState,
        SimulationTrialState,
    )

    persona = Persona(id="tester", name="tester", description="A patient user")
    scenarios = [
        Scenario(
            id="shared",
            task_id=task,
            description="Ask a question",
            persona_refs=[persona.id],
        )
        for task in ("TC-001", "TC-002")
    ]
    state = SimulationState(
        "test",
        [
            SimulationScenarioState(
                s.task_id,
                [
                    SimulationTrialState(
                        s.task_id, persona.id, 1, 1, "pending", None, 20, "", None, None
                    )
                ],
                "pending",
            )
            for s in scenarios
        ],
        2,
    )
    factory = MockRunnerFactory()
    logger = MagicMock()

    def orchestrator(**kwargs):
        record = TrialRecord(
            config=kwargs["trial_config"],
            outcome=TrialOutcome(
                stop_reason="goal_achieved",
                simulated_turns_completed=1,
                duration_seconds=0.1,
            ),
        )
        return MagicMock(execute=AsyncMock(return_value=record))

    with patch("metis.engine.simulation.trial.Orchestrator", side_effect=orchestrator):
        records = await _worker(
            worker_id=0,
            runner_factory=factory,
            worker_trials=[TrialPlanItem(s, persona, 1) for s in scenarios],
            experiment_root=tmp_path,
            fixtures_dir=tmp_path / "fixtures",
            fixture_content_descriptions={},
            console_lock=asyncio.Lock(),
            started_scenarios=set(),
            trial_max_retries=0,
            trial_retry_delay_seconds=0,
            state=state,
            orchestration_logger=logger,
        )
    assert [r.config.task_id for r in records] == ["TC-001", "TC-002"]
    assert all(
        r.config.scenario == "shared" and r.config.trial_index == 1 for r in records
    )
    assert state.completed_trials == 2
    assert [call.args[0] for call in logger.scenario_completed.call_args_list] == [
        "TC-001",
        "TC-002",
    ]
    assert len(list((tmp_path / "outputs" / "trials").glob("*/record.json"))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("retries,expected_attempts", [(None, 3), (0, 1), (1, 2)])
async def test_task_execution_settings_reach_worker_and_failure_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retries: int | None,
    expected_attempts: int,
) -> None:
    from metis.engine.simulation.experiment import expand_trial_plan

    document = Specification.load_file(
        Path("packages/engine/examples/http-agentic_eval_toyapp-1/specification.yaml")
    ).model_dump()
    task = document["tasks"][0]
    task.update(
        max_turns=7, timeout_minutes=2, response_wait_ms=45000, max_run_retries=retries
    )
    specification = Specification.model_validate(document)
    plan = expand_trial_plan(specification, {p.id: p for p in specification.personas})
    plan = [item for item in plan if item.scenario.task_id == task["id"]]
    captured: list[TrialConfig] = []

    class FailingOrchestrator:
        def __init__(self, *, trial_config: TrialConfig, **kwargs: object) -> None:
            captured.append(trial_config)
            if retries == 0:
                raise RuntimeError("setup failed")

        async def execute(self) -> TrialRecord:
            raise RuntimeError("run failed")

        def partial_record(self, reason: str) -> None:
            return None

    monkeypatch.setattr(
        "metis.engine.simulation.trial.Orchestrator", FailingOrchestrator
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    records = await _worker(
        worker_id=0,
        runner_factory=MockRunnerFactory(),
        worker_trials=plan,
        experiment_root=tmp_path,
        fixtures_dir=fixtures,
        fixture_content_descriptions={},
        console_lock=asyncio.Lock(),
        started_scenarios=set(),
        trial_max_retries=2,
        trial_retry_delay_seconds=0,
    )
    assert len(captured) == expected_attempts
    assert len(records) == 1
    assert records[0].max_allowed_attempts == expected_attempts
    assert records[0].attempt_number == expected_attempts
    for config in [*captured, records[0].config]:
        assert (config.max_turns, config.timeout_minutes, config.response_wait_ms) == (
            7,
            2,
            45000,
        )
