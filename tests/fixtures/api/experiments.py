"""Experiment folders that the engine CLI writes, for the API report tests.

`make_experiment` simulates a Specification through `metis engine simulate` with an offline runner
and user, and optionally scores it with `metis engine evaluate` over fake Langfuse traces.
The folders are the same files a real experiment leaves under ``experiments/execute/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import structlog
import yaml
from typer.testing import CliRunner

from metis.engine import cli
from metis.engine.simulation import trial as trial_module
from metis.engine.simulation.runner import Runner
from metis.engine.simulation.types import Observation, Reading, UserAgentOutput
from tests.unit.engine.test_cli_evaluate import _patch_evaluation
from tests.unit.engine.test_cli_simulate import TWO_TRIAL_EXPERIMENT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from metis.core import Artifact
    from metis.core.trials import TrialConfig
    from metis.engine.simulation.types import Promise

    MakeExperiment = Callable[..., Path]


class ReplyRunner(Runner):
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    @property
    def session_id(self) -> str:
        return self.run_dir.name

    async def setup(self, config: TrialConfig) -> None:
        pass

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        return Observation(
            reply="Done", reading=Reading(outcome="completed", why="It replied.")
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        pass

    async def teardown(self) -> None:
        pass


class ReplyRunnerFactory:
    @property
    def retry_defaults(self) -> tuple[int, float]:
        return (0, 0.0)

    async def start(self) -> None:
        pass

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> Runner:
        return ReplyRunner(run_dir)

    async def close(self) -> None:
        pass


class OneTurnUser:
    def __init__(self, **_kwargs: object) -> None:
        pass

    async def decide(
        self, turn: int, held: list[Artifact], promised: list[Promise]
    ) -> UserAgentOutput:
        if turn == 1:
            return UserAgentOutput(
                reasoning="Start.", action="Ask a question", decision="continue"
            )
        return UserAgentOutput(reasoning="Done.", action="", decision="goal_achieved")

    def remember(self, output: UserAgentOutput, observation: Observation) -> None:
        pass


def specification() -> dict[str, Any]:
    """The two-trial engine test Specification, with the offline reply runner."""
    document = yaml.safe_load(TWO_TRIAL_EXPERIMENT)
    document["runner_factory_ref"] = f"{__name__}.ReplyRunnerFactory"
    return document


@pytest.fixture
def make_experiment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[MakeExperiment]:
    """Build the experiment folder under ``tmp_path/experiments/execute`` and return it.

    With ``evaluate=False`` the experiment has trial records but no results.json.
    """
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.setenv("METIS_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setattr(trial_module, "UserAgent", OneTurnUser)
    _patch_evaluation(monkeypatch, traces=1)
    runner = CliRunner()
    executions = tmp_path / "experiments" / "execute"

    def _make(*, evaluate: bool = True) -> Path:
        input_dir = tmp_path / "sources"
        input_dir.mkdir()
        (input_dir / "specification.yaml").write_text(yaml.safe_dump(specification()))
        simulation = runner.invoke(
            cli.app,
            [
                "simulate",
                "--input-dir",
                str(input_dir),
                "--project-dir",
                str(tmp_path),
                "--no-tui",
            ],
        )
        assert simulation.exit_code == 0, simulation.output
        (experiment_dir,) = executions.iterdir()
        if evaluate:
            evaluation = runner.invoke(
                cli.app, ["evaluate", "--experiment-dir", str(experiment_dir)]
            )
            assert evaluation.exit_code == 0, evaluation.output
        # The engine CLI sends structlog to an experiment log file that is closed by now.
        structlog.reset_defaults()
        return experiment_dir

    yield _make
    structlog.reset_defaults()
