from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml
from tests.unit.engine.test_cli_evaluate import _patch_evaluation
from tests.unit.engine.test_cli_simulate import TWO_TRIAL_EXPERIMENT
from typer.testing import CliRunner

from metis.core import Artifact, resolve_artifact_path
from metis.core.reporting import EvaluationResults
from metis.core.trials import TrialConfig, TrialRecord
from metis.engine import cli
from metis.engine.simulation import trial as trial_module
from metis.engine.simulation.runner import Runner
from metis.engine.simulation.types import (
    Observation,
    Promise,
    Reading,
    UserAgentOutput,
)
from metis.wizard.application.compile.specification import (
    SpecificationFixture,
    build_specification_archive,
)


class FileRunner(Runner):
    def __init__(self, run_dir: Path, fixtures_dir: Path) -> None:
        self.run_dir = run_dir
        self.fixtures_dir = fixtures_dir

    @property
    def session_id(self) -> str:
        return self.run_dir.name

    async def setup(self, config: TrialConfig) -> None:
        assert config.fixtures == ["input.txt"]

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        content = (self.fixtures_dir / "input.txt").read_bytes()
        self.ledger.record_upload("input.txt", at_simulated_turn=1)
        self.ledger.record_download(
            "answer.bin", content + b" processed", at_simulated_turn=1
        )
        return Observation(
            reply="File processed",
            reading=Reading(outcome="completed", why="The file was processed."),
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        pass

    async def teardown(self) -> None:
        pass


class FileRunnerFactory:
    @property
    def retry_defaults(self) -> tuple[int, float]:
        return (0, 0.0)

    async def start(self) -> None:
        pass

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> Runner:
        return FileRunner(run_dir, fixtures_dir)

    async def close(self) -> None:
        pass


class ScriptedUser:
    def __init__(self, **_kwargs: object) -> None:
        pass

    async def decide(
        self, turn: int, held: list[Artifact], promised: list[Promise]
    ) -> UserAgentOutput:
        if turn == 1:
            return UserAgentOutput(
                reasoning="Start.", action="⟦Process the file⟧", decision="continue"
            )
        return UserAgentOutput(reasoning="Done.", action="", decision="goal_achieved")

    def remember(self, output: UserAgentOutput, observation: Observation) -> None:
        pass


@pytest.mark.parametrize("source", ["folder", "wizard_archive"])
def test_execution_can_resume_and_report_after_move(
    tmp_path: Path, source: str
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; import pytest; "
            "from tests.integration.engine.test_execution_layout import _exercise; "
            "_exercise(pytest.MonkeyPatch(), Path(sys.argv[1]), sys.argv[2])",
            str(tmp_path),
            source,
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _exercise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str) -> None:
    document = yaml.safe_load(TWO_TRIAL_EXPERIMENT)
    document["runner_factory_ref"] = f"{__name__}.FileRunnerFactory"
    document["tasks"][0]["fixtures"] = ["input.txt"]
    document["fixture_content_descriptions"] = {"input.txt": "Input bytes"}
    design_dir = tmp_path / "experiments" / "design"
    if source == "wizard_archive":
        archive = build_specification_archive(
            document, [SpecificationFixture("input.txt", io.BytesIO(b"fixture"))]
        )
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            bundle.extractall(design_dir)
        input_dir = next(design_dir.glob("*/outputs"))
    else:
        input_dir = tmp_path / "user-supplied"
        (input_dir / "fixtures").mkdir(parents=True)
        (input_dir / "fixtures" / "input.txt").write_bytes(b"fixture")
        (input_dir / "specification.yaml").write_text(yaml.safe_dump(document))

    monkeypatch.setattr(cli, "_find_project_root", lambda: tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.setenv("METIS_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setattr(trial_module, "UserAgent", ScriptedUser)
    _patch_evaluation(monkeypatch, traces=1)
    runner = CliRunner()
    simulation = runner.invoke(
        cli.app, ["simulate", "--input-dir", str(input_dir), "--no-tui"]
    )
    assert simulation.exit_code == 0, simulation.output
    execution = next((tmp_path / "experiments" / "execute").iterdir())
    records = sorted((execution / "outputs" / "trials").glob("*/record.json"))
    assert len(records) == 2
    snapshot = execution / "inputs"
    assert yaml.safe_load((snapshot / "specification.yaml").read_text()) == document
    assert (snapshot / "fixtures" / "input.txt").read_bytes() == b"fixture"
    for record_path in records:
        record = TrialRecord.model_validate_json(record_path.read_text())
        assert record.outcome.stop_reason == "goal_achieved"
        assert {artifact.source for artifact in record.artifacts} == {
            "fixture",
            "target",
        }
        for artifact in record.artifacts:
            assert artifact.path is not None and not Path(artifact.path).is_absolute()
            local = resolve_artifact_path(execution, artifact.path)
            assert local is not None and local.is_file()
            assert artifact.digest is not None
        log = record_path.parent / "simulate.log"
        assert log.is_symlink() and log.is_file()
        assert log.resolve().parent == execution / "logs"
        assert log.resolve().name.startswith("simulate-")
        assert (record_path.parent / "artifacts" / "run-manifest.json").is_file()
    assert (execution / "logs" / "simulate.log").is_file()

    complete_bytes = records[0].read_bytes()
    records[1].unlink()
    stale = records[1].parent / "artifacts" / "answer.bin"
    stale.write_bytes(b"interrupted")
    (records[1].parent / "simulate.log").write_text("Interrupted attempt\n")
    (input_dir / "fixtures" / "input.txt").write_bytes(b"changed source")
    moved = tmp_path / "moved execution"
    execution.rename(moved)
    log_dir = moved / ("custom logs" if source == "wizard_archive" else "logs")
    log_options = ["--log-dir", str(log_dir)] if source == "wizard_archive" else []
    resumed = runner.invoke(
        cli.app,
        ["run", "--resume", "--experiment-dir", str(moved), "--no-tui", *log_options],
    )
    assert resumed.exit_code == 0, resumed.output
    trials = moved / "outputs" / "trials"
    assert (
        trials / records[0].parent.name / "record.json"
    ).read_bytes() == complete_bytes
    resumed_trial = trials / records[1].parent.name
    assert (
        resumed_trial / "artifacts" / "answer.bin"
    ).read_bytes() == b"fixture processed"
    quarantined = list(resumed_trial.glob("artifacts-superseded-*/answer.bin"))
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == b"interrupted"
    assert (resumed_trial / "simulate.log").is_file()
    assert (resumed_trial / "simulate.log").resolve().parent == log_dir
    assert (log_dir / "simulate.log").is_file()
    if source == "folder":
        assert "RESUMED" in (resumed_trial / "simulate.log").read_text()

    evaluation = runner.invoke(cli.app, ["evaluate", "--experiment-dir", str(moved)])
    assert evaluation.exit_code == 0, evaluation.output
    reports = moved / "outputs" / "reports"
    results_file = reports / "results.json"
    results = EvaluationResults.load_file(results_file)
    # This checks results.json directly instead of running the report command through it.
    assert len(results.records) == 2
    assert "RESULTS WRITTEN" in (moved / "logs" / "evaluate.log").read_text()
    for record_path in trials.glob("*/record.json"):
        record = TrialRecord.model_validate_json(record_path.read_text())
        for artifact in record.artifacts:
            local = resolve_artifact_path(moved, artifact.path)
            assert local is not None and local.is_file()
