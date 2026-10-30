"""Running graders on sessions: the step between ``fetch_session`` and ``results.json``.

Each criterion's grader is built once, as ``SomeGrader(args)``, and run once per session of
every task whose behaviours include that criterion. Every grader run gets the whole session as
one read-only ``GradingInput`` and the shared ``LLMSettings``; the grader decides what to judge.
Grader runs on one session execute concurrently, each on its own deep copy of the input.
Nothing here caps them: the cap on grader LLM
calls lives in the shared client's connection pool (see ``judge.py``).

The grader scores; this module decides the outcome. Each scored ``GraderResult`` becomes
``passed`` when ``score >= threshold`` and ``failed`` otherwise, using the criterion's
``threshold``. Skipped and errored results pass through. Two rules make every grader run leave a
visible record: an empty ``GradingOutput`` and a ``grade()`` that raises are each recorded as one
errored result, so a broken grader can never vanish from a report or drag a pass rate down.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from metis.core.grading import GraderResult, GradingOutput, RecordedResult
from metis.core.logging import get_logger
from metis.core.reporting import GraderRecord
from metis.engine.evaluation.judge import resolve_grader_args
from metis.engine.tracing import traced
from metis.library.grader import Grader

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from metis.core.profile import Criterion
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings

logger = get_logger(__name__)


class GraderSetupError(ValueError):
    """A criterion's grader cannot be built: a bad FQN, a non-grader class, or bad args.

    The message names the criterion and is meant to be shown to the user as-is.
    """


@dataclass(frozen=True)
class SessionFacts:
    """The run facts a ``GraderRecord`` carries about the session it graded."""

    session_id: str
    scenario_id: str
    task_id: str
    trial_index: int
    trace_session_id: str | None = None
    """The trial's session in the METIS-internal Langfuse (``tracing.trial_session_id``), so
    its grading traces sit beside its simulation traces."""


def resolve_grader_class(fqn: str) -> type[Grader[Any]]:
    """Import ``fqn`` and check that it names a concrete ``Grader`` subclass."""
    module_path, _, class_name = fqn.rpartition(".")
    if not module_path:
        raise GraderSetupError(f"grader '{fqn}' is not a fully-qualified name")
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # any import-time failure is a setup error, not a crash
        raise GraderSetupError(
            f"grader '{fqn}' could not be imported: {type(exc).__name__}: {exc}"
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise GraderSetupError(
            f"grader '{fqn}' could not be imported: "
            f"module '{module_path}' has no attribute '{class_name}'"
        )
    if not (isinstance(cls, type) and issubclass(cls, Grader)):
        raise GraderSetupError(
            f"grader '{fqn}' is not a subclass of metis.library.grader.Grader"
        )
    if inspect.isabstract(cls) or not hasattr(cls, "args_model"):
        raise GraderSetupError(
            f"grader '{fqn}' is an abstract base, not a concrete grader"
        )
    return cls


def build_grader(
    criterion: Criterion,
    *,
    default_judge_model: str | None,
    env: Mapping[str, str],
) -> Grader[Any]:
    """Resolve, fill in the judge model, validate and build one criterion's grader.

    Raises ``GraderSetupError`` naming the criterion for every way this can fail, so the
    pre-run pass can report it before anything runs.
    """
    if not criterion.grader_fqn:
        raise GraderSetupError(f"Criterion '{criterion.id}' has no grader_fqn")
    try:
        cls = resolve_grader_class(criterion.grader_fqn)
    except GraderSetupError as exc:
        raise GraderSetupError(f"Criterion '{criterion.id}': {exc}") from exc
    try:
        raw = resolve_grader_args(
            cls.args_model,
            criterion.grader_args,
            default_judge_model=default_judge_model,
            env=env,
            description=criterion.description,
        )
    except ValueError as exc:
        raise GraderSetupError(f"Criterion '{criterion.id}': {exc}") from exc
    try:
        args = cls.args_model.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'grader_args'}: {error['msg']}"
            for error in exc.errors()
        )
        raise GraderSetupError(
            f"Criterion '{criterion.id}' has invalid grader_args for {criterion.grader_fqn}: {problems}"
        ) from exc
    try:
        return cls(args)
    except ValueError as exc:
        raise GraderSetupError(f"Criterion '{criterion.id}': {exc}") from exc


def record_results(output: GradingOutput, threshold: float) -> list[RecordedResult]:
    """Apply the threshold rule to one grader run's output.

    An empty output breaks the "never return ``[]``" rule and becomes one errored result.
    """
    if not output.results:
        return [
            RecordedResult(
                outcome="errored",
                reason="The grader returned no results; a grader that cannot judge the "
                "session must return an errored result with the reason.",
            )
        ]
    return [_record(result, threshold) for result in output.results]


def _record(result: GraderResult, threshold: float) -> RecordedResult:
    if result.status == "scored":
        assert result.score is not None  # guaranteed by GraderResult's validator
        outcome = "passed" if result.score >= threshold else "failed"
        return RecordedResult(
            outcome=outcome,
            score=result.score,
            reason=result.reason,
            scope=result.scope,
        )
    return RecordedResult(
        outcome=result.status,
        reason=result.reason,
        scope=result.scope,
    )


def _trace_output(output: object) -> object:
    """A grader run's results as its trace output: the status, score and reason of each."""
    if not isinstance(output, GradingOutput):
        return None
    return [
        result.model_dump(include={"status", "score", "reason"})
        for result in output.results
    ]


async def _run_one(
    criterion: Criterion,
    grader: Grader[Any],
    grading_input: GradingInput,
    llm: LLMSettings,
    facts: SessionFacts,
) -> GraderRecord:
    """One grader run, always ending in a record: a raised exception becomes one errored result.

    The grader gets its own deep copy of the input. The models are frozen, but the dicts
    inside ``input``/``output``/``metadata`` are not, and every grader run on a session
    executes concurrently, so a grader that edits a payload in place would otherwise change
    what the others see.

    The run is one trace in the METIS-internal Langfuse, named by the criterion, with the
    grader's results as its output. The grader's judge calls name no Langfuse client, so
    ``traced`` names it for them.
    """
    assert criterion.grader_fqn is not None
    try:
        output = await traced(
            lambda: grader.grade(grading_input.model_copy(deep=True), llm),
            name=criterion.id,
            session_id=facts.trace_session_id,
            metadata={
                "criterion_id": criterion.id,
                "grader_fqn": criterion.grader_fqn,
                "session_id": facts.session_id,
                "scenario_id": facts.scenario_id,
                "task_id": facts.task_id,
                "trial_index": facts.trial_index,
            },
            output=_trace_output,
        )
        if not isinstance(output, GradingOutput):
            raise TypeError(
                f"grade() returned {type(output).__name__}, not GradingOutput"
            )
        results = record_results(output, grader.args.threshold)
    except Exception as exc:  # a grader bug must not take down the other grader runs
        logger.exception(
            "[evaluation] grader %s raised on criterion %s, session %s",
            criterion.grader_fqn,
            criterion.id,
            facts.session_id,
        )
        results = [
            RecordedResult(
                outcome="errored", reason=f"Grader raised: {type(exc).__name__}: {exc}"
            )
        ]
    return GraderRecord(
        session_id=facts.session_id,
        scenario_id=facts.scenario_id,
        task_id=facts.task_id,
        trial_index=facts.trial_index,
        criterion_id=criterion.id,
        grader_fqn=criterion.grader_fqn,
        grader_args=grader.args.model_dump(mode="json"),
        aggregation=_aggregation(grader),
        results=results,
    )


def _aggregation(grader: Grader[Any]) -> str | None:
    if getattr(grader, "taxonomy", None) is None:
        return None
    return str(grader.aggregation)


async def grade_session(
    criteria: Sequence[Criterion],
    graders: Mapping[str, Grader[Any]],
    grading_input: GradingInput,
    llm: LLMSettings,
    facts: SessionFacts,
) -> list[GraderRecord]:
    """Run every grader once on one session, concurrently, one record each, in input order."""
    return list(
        await asyncio.gather(
            *(
                _run_one(criterion, graders[criterion.id], grading_input, llm, facts)
                for criterion in criteria
            )
        )
    )
