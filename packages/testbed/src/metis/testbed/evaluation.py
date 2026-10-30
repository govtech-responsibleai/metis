"""Run, save, and compare Wizard specification evaluations."""

from __future__ import annotations

import io
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml
from pydantic import JsonValue, TypeAdapter

from metis.core.specification import Specification
from metis.testbed.calculation import calculate_scores
from metis.testbed.contracts import (
    AggregateLevel,
    AggregateScores,
    BehaviourNNSummary,
    Candidate,
    CaseConfig,
    CaseResult,
    CaseStatus,
    EvaluationConfig,
    EvaluationProgress,
    EvaluationRecord,
    EvaluationRequest,
    InteractionDriver,
    InteractionEvent,
    InteractionMode,
    LevelScore,
    Similarity,
    VersionComparison,
    WizardInput,
    WizardState,
    WizardTarget,
)
from metis.testbed.scoring import compare_specifications
from metis.testbed.use_cases import load_case
from metis.wizard import (
    AnyResponse,
    CapabilityConfidence,
    InterviewDocument,
    InterviewEndRequest,
    InterviewFailure,
    InterviewStartRequest,
    InterviewSuccess,
    InterviewTurnRequest,
    SpecificationFixture,
    extract_documents,
    handle_interview,
)
from metis.wizard.application.matching import GraderMatcher
from metis.wizard.contracts.conversation import AnyRequest, options_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from metis.wizard.application.interviewer import Interviewer
    from metis.wizard.application.matching import GraderSelector

LEVELS = ("features", "behaviours", "criteria", "graders", "tasks")


class MissingCaseInput(FileNotFoundError):
    """A configured Test Case cannot run because an input is unavailable."""


class WizardTargetError(RuntimeError):
    """Keep the complete failure returned by a Wizard operation."""

    def __init__(self, failure: InterviewFailure) -> None:
        self.failure = failure
        self.events: list[InteractionEvent] = []
        details = (
            "; ".join(item.message for item in failure.missing)
            or failure.diagnostic_message
            or ""
        )
        super().__init__(
            f"{failure.code}: {failure.message}" + (f" {details}" if details else "")
        )


class MetisWizardTarget:
    """Translate the METIS headless Interview interface into testbed states."""

    name = "metis-wizard"

    def __init__(self, interviewer: Interviewer) -> None:
        self._interviewer = interviewer
        self._matcher = GraderMatcher(selector=cast("GraderSelector", interviewer))

    def _state(self, result: object) -> WizardState:
        if isinstance(result, InterviewFailure):
            raise WizardTargetError(result)
        if not isinstance(result, InterviewSuccess):
            raise TypeError("The Wizard returned an unknown result.")
        return WizardState(
            raw=result.state,
            specification=result.state.specification,
            outcome=result.outcome,
            stage=str(result.stage),
            pending=result.state.pending.model_dump(mode="json")
            if result.state.pending is not None
            else None,
            raw_output=result.state.specification.model_dump(mode="json"),
        )

    def start(self, evidence: WizardInput) -> WizardState:
        result = handle_interview(
            InterviewStartRequest(
                description=evidence.description,
                known_capability_ids=[],
                capability_confidence=CapabilityConfidence.LOW,
                documents=[
                    InterviewDocument(name=name, text=text)
                    for name, text in evidence.documents
                ],
            ),
            interviewer=self._interviewer,
            matcher=self._matcher,
        )
        return self._state(result)

    def respond(self, state: WizardState, response: object) -> WizardState:
        pending = state.raw.pending
        if pending is None or pending.request_id is None:
            raise ValueError("The Wizard has no pending request to answer.")
        result = handle_interview(
            InterviewTurnRequest(
                state=state.raw,
                request_id=pending.request_id,
                response=TypeAdapter(AnyResponse).validate_python(response),
            ),
            interviewer=self._interviewer,
            matcher=self._matcher,
        )
        return self._state(result)

    def end(self, state: WizardState) -> WizardState:
        result = handle_interview(
            InterviewEndRequest(state=state.raw),
            interviewer=self._interviewer,
            matcher=self._matcher,
        )
        return self._state(result)


class OneShotInteraction:
    """Start an Interview and immediately ask the Target to finish it."""

    mode = InteractionMode.ONE_SHOT

    def run(self, target: WizardTarget, evidence: WizardInput) -> Candidate:
        events: list[InteractionEvent] = []

        def record(
            operation: str, state: WizardState, response: JsonValue = None
        ) -> None:
            events.append(
                InteractionEvent(
                    operation=operation,
                    outcome=state.outcome,
                    stage=state.stage,
                    request=state.pending,
                    response=response,
                )
            )

        try:
            started = target.start(evidence)
            record("start", started)
            finished = target.end(started)
            record("end", finished)
            # The evaluation policy accepts the generated Scenario review once. It does not
            # invent clarification answers or bypass a disabled readiness gate.
            if (
                finished.outcome == "awaiting_response"
                and finished.stage == "scenarios"
                and finished.pending
            ):
                pending = TypeAdapter(AnyRequest).validate_python(finished.pending)
                selected = [
                    key
                    for key, option in options_of(pending).items()
                    if option.id.action == "continue" and option.enabled
                ]
                if len(selected) == 1:
                    response: dict[str, JsonValue] = {
                        "type": "choice",
                        "selected": list(selected),
                    }
                    finished = target.respond(finished, response)
                    record("accept_review", finished, response)
        except WizardTargetError as exc:
            exc.events = events
            raise
        return Candidate(
            specification=finished.specification,
            outcome=finished.outcome,
            events=events,
            raw_output=finished.raw_output,
        )


def _read_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_config(path: Path) -> EvaluationConfig:
    config = EvaluationConfig.model_validate(_read_yaml(path))
    if len(config.cases) != len(set(config.cases)):
        raise ValueError("config.yaml contains the same Test Case more than once.")
    return config


def _evidence(case: CaseConfig, root: Path) -> WizardInput:
    if not case.inputs:
        raise MissingCaseInput(root / "inputs")
    prompt_name = "inputs/prompt.md"
    if prompt_name not in case.inputs:
        raise MissingCaseInput(root / prompt_name)
    paths = [(root / relative).resolve() for relative in case.inputs]
    for relative, path in zip(case.inputs, paths, strict=True):
        if not path.is_relative_to(root.resolve()):
            raise ValueError(f"Input is outside Test Case {case.id}: {relative}")
        if not path.is_file():
            raise MissingCaseInput(relative)

    prompt = (root / prompt_name).read_text(encoding="utf-8-sig")
    supporting_paths = [
        path
        for relative, path in zip(case.inputs, paths, strict=True)
        if relative != prompt_name
    ]
    text_formats = {".md", ".txt", ".yaml", ".yml", ".json", ".csv"}
    fixtures = [
        SpecificationFixture(name=path.name, stream=io.BytesIO(path.read_bytes()))
        for path in supporting_paths
        if path.suffix.lower() not in text_formats
    ]
    extracted_documents = extract_documents(fixtures).documents if fixtures else []
    return WizardInput(
        case_id=case.id,
        description=prompt,
        documents=[
            (path.name, path.read_text(encoding="utf-8-sig"))
            for path in supporting_paths
            if path.suffix.lower() in text_formats
        ]
        + [(item.name, item.text) for item in extracted_documents],
    )


def _aggregate_level(results: list[CaseResult], name: str) -> AggregateLevel:
    levels: list[LevelScore] = []
    for result in results:
        if result.scores is not None:
            levels.append(getattr(result.scores, name))
    values = [level.similarity for level in levels if level.similarity is not None]
    weighted_denominator = sum(
        max(level.reference_count, level.generated_count)
        for level in levels
        if level.similarity is not None
    )
    weighted_numerator = sum(
        (level.similarity or 0.0) * max(level.reference_count, level.generated_count)
        for level in levels
        if level.similarity is not None
    )
    return AggregateLevel(
        case_average=sum(values) / len(values) if values else None,
        item_weighted=(weighted_numerator / weighted_denominator)
        if weighted_denominator
        else None,
        scored_cases=len(values),
    )


def _aggregate(results: list[CaseResult]) -> AggregateScores:
    return AggregateScores(**{name: _aggregate_level(results, name) for name in LEVELS})


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not safe:
        raise ValueError(
            "Target names and versions need at least one filename-safe character."
        )
    return safe


def _render_report(record: EvaluationRecord) -> str:
    lines = [
        f"# Wizard evaluation: {record.target_version}",
        "",
        f"- Target: `{record.target}`",
        f"- Target version: `{record.target_version}`",
        f"- Created: `{record.created_at.isoformat()}`",
        f"- Interaction: `{record.interaction}`",
        f"- Configuration: `{record.config}` version {record.config_version}",
        "",
        "## Scores",
        "",
        "| Test Case | Feature | Expected Behaviour | Criterion | Grader | Task | Status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]

    def value(score: float | None) -> str:
        return f"{score:.3f}" if score is not None else "—"

    for result in record.cases:
        scores = result.scores
        fields = (
            [value(getattr(scores, name).similarity) for name in LEVELS]
            if scores is not None
            else ["—"] * len(LEVELS)
        )
        lines.append(f"| {result.case_id} | {' | '.join(fields)} | {result.status} |")
    aggregate = [value(getattr(record.aggregate, name).case_average) for name in LEVELS]
    weighted = [value(getattr(record.aggregate, name).item_weighted) for name in LEVELS]
    lines.extend(
        [
            f"| Case average | {' | '.join(aggregate)} | — |",
            f"| Item weighted | {' | '.join(weighted)} | — |",
            "",
        ]
    )
    lines.extend(
        [
            "## Behaviour overlap (experimental)",
            "",
            "Mean nearest-neighbour similarity measures overlap within each set. Lower means less similarity to the closest neighbours. Compare behaviour counts; this is not a coverage score or a pass/fail gate. A set with fewer than two behaviours has no score.",
            "",
            "| Test Case | Text version | Reference count | Generated count | Reference mean NN | Generated mean NN |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for result in record.cases:
        for version, summary in result.behaviour_nn.items():
            lines.append(
                f"| {result.case_id} | {version} | {summary.reference_count} | {summary.generated_count} | {value(summary.reference_mean_nn)} | {value(summary.generated_mean_nn)} |"
            )
    lines.extend(["", "## Differences", ""])
    for result in record.cases:
        lines.extend([f"### {result.case_id}", ""])
        lines.extend(
            [
                f"Interview completed: {result.completed}. Outcome: {result.lifecycle_outcome}.",
                "",
            ]
        )
        if result.error:
            lines.extend([result.error, ""])
        if result.failure:
            lines.extend(
                [
                    "```json",
                    json.dumps(result.failure, indent=2, ensure_ascii=False),
                    "```",
                    "",
                ]
            )
        if result.scores is None:
            lines.extend(["No scores were produced.", ""])
            continue
        if result.score_report is not None:
            lines.extend(
                [f"[All metrics and behaviour pair scores]({result.score_report})", ""]
            )
        for name in LEVELS:
            score = getattr(result.scores, name)
            lines.append(f"#### {name.title()}")
            lines.append("")
            lines.append(
                f"Similarity {value(score.similarity)}; reference {score.reference_count}; "
                f"generated {score.generated_count}."
            )
            lines.append("")
            if score.matches:
                lines.extend(
                    [
                        "| Reference | Generated | Similarity | Details |",
                        "|---|---|---:|---|",
                        *[
                            f"| {item.reference_id} | {item.generated_id} | "
                            f"{item.similarity:.3f} | "
                            f"{', '.join(f'{key}={value:.3f}' if value is not None else f'{key}=—' for key, value in item.details.items())} |"
                            for item in score.matches
                        ],
                        "",
                    ]
                )
            if score.missing:
                lines.extend([f"Missing: {', '.join(score.missing)}", ""])
            if score.additional:
                lines.extend([f"Additional: {', '.join(score.additional)}", ""])
    return "\n".join(lines).rstrip() + "\n"


def _save(
    request: EvaluationRequest,
    record: EvaluationRecord,
    generated: dict[str, Specification],
) -> Path:
    target = _safe_segment(record.target)
    version = _safe_segment(record.target_version)
    output = request.results_root / target / version / record.id
    output.mkdir(parents=True, exist_ok=True)
    (output / "run.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (output / "report.md").write_text(_render_report(record), encoding="utf-8")
    cases_root = output / "cases"
    for result in record.cases:
        case_root = cases_root / _safe_segment(result.case_id)
        case_root.mkdir(parents=True, exist_ok=True)
        (case_root / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        specification = generated.get(result.case_id)
        if specification is not None:
            (case_root / "generated-specification.yaml").write_text(
                yaml.safe_dump(
                    specification.model_dump(mode="json"),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
    return output


def run_evaluation(
    request: EvaluationRequest,
    *,
    target: WizardTarget,
    interaction: InteractionDriver,
    similarity: Similarity | None = None,
    clock: Callable[[], datetime] | None = None,
    on_progress: Callable[[EvaluationProgress], None] | None = None,
) -> tuple[EvaluationRecord, Path]:
    """Run every configured Test Case and save one immutable result."""
    config = _load_config(request.config_path)
    now = (clock or (lambda: datetime.now(UTC)))()
    run_id = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        request.results_root
        / _safe_segment(target.name)
        / _safe_segment(request.target_version)
        / run_id
    )
    output.mkdir(parents=True, exist_ok=False)
    results: list[CaseResult] = []
    generated: dict[str, Specification] = {}
    total = len(config.cases)

    def report(case_id: str, completed: int, phase: str) -> None:
        if on_progress is not None:
            on_progress(
                EvaluationProgress(
                    case_id=case_id,
                    completed=completed,
                    total=total,
                    phase=phase,
                )
            )

    for index, relative in enumerate(config.cases):
        case_id = Path(relative).name
        report(case_id, index, "preparing inputs")
        candidate: Candidate | None = None
        try:
            case, root = load_case(request.config_path.parent, relative)
            evidence = _evidence(case, root)
            report(case.id, index, "running Wizard")
            candidate = interaction.run(target, evidence)
            generated[case.id] = candidate.specification
            report(case.id, index, "scoring")
            reference_path = (root / case.expected_output).resolve()
            if not reference_path.is_relative_to(root.resolve()):
                raise ValueError(
                    f"Reference is outside Test Case {case.id}: {case.expected_output}"
                )
            score_report = None
            behaviour_nn: dict[str, BehaviourNNSummary] = {}
            if similarity is None:
                case_root = output / "cases" / _safe_segment(case.id)
                case_root.mkdir(parents=True, exist_ok=True)
                generated_path = case_root / "generated-specification.yaml"
                generated_path.write_text(
                    yaml.safe_dump(
                        candidate.specification.model_dump(mode="json"),
                        sort_keys=False,
                        allow_unicode=True,
                    ),
                    encoding="utf-8",
                )
                calculation = calculate_scores(
                    generated_path, reference=reference_path, report_directory=case_root
                )
                scores = calculation.scores
                behaviour_nn = {
                    version.value: BehaviourNNSummary(
                        reference_count=len(analysis.reference.ids),
                        generated_count=len(analysis.generated.ids),
                        reference_mean_nn=analysis.reference.mean_nn_similarity,
                        generated_mean_nn=analysis.generated.mean_nn_similarity,
                    )
                    for version, analysis in calculation.behaviour_analysis.items()
                    if analysis.generated is not None
                }
                score_report = (
                    f"cases/{_safe_segment(case.id)}/generated-specification.scores.md"
                )
            else:
                reference = Specification.model_validate(_read_yaml(reference_path))
                scores = compare_specifications(
                    candidate.specification, reference, similarity
                )
            result = CaseResult(
                case_id=case.id,
                status=CaseStatus.SCORED
                if candidate.outcome == "done"
                else CaseStatus.INCOMPLETE,
                completed=candidate.outcome == "done",
                lifecycle_outcome=candidate.outcome,
                scores=scores,
                behaviour_nn=behaviour_nn,
                score_report=score_report,
                events=candidate.events,
                raw_output=candidate.raw_output,
                generated_specification=(
                    f"cases/{_safe_segment(case.id)}/generated-specification.yaml"
                ),
            )
        except WizardTargetError as exc:
            diagnostic = exc.failure.diagnostic_state or exc.failure.state
            if diagnostic is not None:
                generated[case_id] = diagnostic.specification
            result = CaseResult(
                case_id=case_id,
                status=CaseStatus.FAILED,
                lifecycle_outcome="failed",
                error=str(exc),
                failure=exc.failure.model_dump(mode="json"),
                events=exc.events,
                generated_specification=(
                    f"cases/{_safe_segment(case_id)}/generated-specification.yaml"
                    if diagnostic is not None
                    else None
                ),
            )
        except MissingCaseInput as exc:
            result = CaseResult(
                case_id=case_id,
                status=CaseStatus.INPUT_MISSING,
                error=f"Missing configured input: {exc}",
            )
        except Exception as exc:  # one Test Case must not stop the complete evaluation
            result = CaseResult(
                case_id=case_id,
                status=CaseStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                lifecycle_outcome=candidate.outcome if candidate else None,
                completed=candidate is not None and candidate.outcome == "done",
                events=candidate.events if candidate else [],
                raw_output=candidate.raw_output if candidate else None,
                generated_specification=(
                    f"cases/{_safe_segment(case_id)}/generated-specification.yaml"
                    if case_id in generated
                    else None
                ),
            )
        results.append(result)
        report(case_id, index + 1, result.status.value.replace("_", " "))
    record = EvaluationRecord(
        id=run_id,
        created_at=now,
        target=target.name,
        target_version=request.target_version,
        interaction=interaction.mode,
        config=config.id,
        config_version=config.version,
        cases=results,
        aggregate=_aggregate(results),
    )
    return record, _save(request, record, generated)


def detect_target_version(repository: Path) -> str:
    """Use an exact Wizard tag, then the current branch, as the human version name."""

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    tag = git("describe", "--tags", "--exact-match", "--match", "metis-wizard/v*")
    if tag:
        return tag
    branch = git("branch", "--show-current")
    if branch:
        return branch
    raise ValueError("Could not identify the Wizard version. Supply --target-version.")


def _latest(results_root: Path, target: str, version: str) -> EvaluationRecord:
    directory = results_root / _safe_segment(target) / _safe_segment(version)
    candidates = sorted(path for path in directory.iterdir() if path.is_dir())
    if not candidates:
        raise FileNotFoundError(f"No saved result for {target} {version}.")
    return EvaluationRecord.model_validate_json(
        (candidates[-1] / "run.json").read_text(encoding="utf-8")
    )


def compare_versions(
    results_root: Path,
    *,
    target: str,
    older_version: str,
    newer_version: str,
) -> VersionComparison:
    """Compare the latest saved execution for two Target versions."""
    older = _latest(results_root, target, older_version)
    newer = _latest(results_root, target, newer_version)
    changes: dict[str, float | None] = {}
    for name in LEVELS:
        old = getattr(older.aggregate, name).case_average
        new = getattr(newer.aggregate, name).case_average
        changes[name] = new - old if old is not None and new is not None else None
    older_cases = {item.case_id: item for item in older.cases}
    newer_cases = {item.case_id: item for item in newer.cases}
    case_changes: dict[str, dict[str, float | None]] = {}
    for case_id in sorted(older_cases.keys() & newer_cases.keys()):
        old_scores = older_cases[case_id].scores
        new_scores = newer_cases[case_id].scores
        case_changes[case_id] = {}
        for name in LEVELS:
            old = getattr(old_scores, name).similarity if old_scores else None
            new = getattr(new_scores, name).similarity if new_scores else None
            case_changes[case_id][name] = (
                new - old if old is not None and new is not None else None
            )
    return VersionComparison(
        target=target,
        older_version=older_version,
        newer_version=newer_version,
        older_id=older.id,
        newer_id=newer.id,
        changes=changes,
        case_changes=case_changes,
    )


__all__ = [
    "MetisWizardTarget",
    "MissingCaseInput",
    "OneShotInteraction",
    "compare_versions",
    "detect_target_version",
    "run_evaluation",
]
