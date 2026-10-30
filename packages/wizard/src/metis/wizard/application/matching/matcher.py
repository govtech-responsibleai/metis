"""Criterion → grader FQN, by one model call over the grader library.

The matcher is a separate call. The model that drafts a Criterion never writes its grader, so the
patch rule that forbids `grader_fqn` stays true. The model reads the library graders under their
Measures and suggests one grader for each Criterion, or no grader. No grader, an FQN that is not
offered, or a failed call gives the criterion judge, which takes its instructions from the
Criterion description. So a failed call degrades the experiment and never stops the Interview.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import ValidationError

from metis.core.logging import get_logger
from metis.library.grader import Grader, JudgeArgs, criterion_judge_args
from metis.wizard.application import prompts
from metis.wizard.application.matching.library_catalogue import library_catalogue

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metis.wizard.contracts.grader_spec import GraderSpec
    from metis.wizard.contracts.output import GraderChoices
    from metis.wizard.domain.specification import Behaviour, Criterion, Specification

# The grader the matcher selects when no library grader fits a criterion.
CRITERION_JUDGE_FQN = "metis.library.graders.CriterionJudgeGrader"

logger = get_logger(__name__)


class GraderSelector(Protocol):
    def select_graders(
        self,
        prompt: prompts.ModelPrompt,
        offered: set[str],
        criterion_ids: set[str],
    ) -> GraderChoices: ...


def check_grader_choices(
    choices: GraderChoices, offered: set[str], criterion_ids: set[str]
) -> None:
    """Raise ``ValueError`` when the reply names an FQN or a Criterion that the call did not send."""
    returned = [choice.criterion_id for choice in choices.choices]
    problems = []
    if missing := criterion_ids - set(returned):
        problems.append(
            f"Give one choice for each Criterion: {', '.join(sorted(missing))}."
        )
    if unknown := set(returned) - criterion_ids:
        problems.append(f"Unknown Criterion IDs: {', '.join(sorted(unknown))}.")
    if len(returned) != len(set(returned)):
        problems.append("Give only one choice for each Criterion.")
    if not_offered := {c.grader for c in choices.choices if c.grader} - offered:
        problems.append(
            f"Use only an offered grader FQN or null: {', '.join(sorted(not_offered))}."
        )
    if problems:
        raise ValueError(" ".join(problems))


def _criterion_payload(
    criterion: Criterion, behaviour: Behaviour | None
) -> dict[str, Any]:
    return {
        "id": criterion.id,
        "name": criterion.name,
        "description": str(criterion.description),
        "behaviour": (
            {"name": behaviour.name, "description": behaviour.description}
            if behaviour is not None
            else None
        ),
    }


@dataclass
class GraderMatcher:
    """Ask the model for the library grader that fits each Criterion, or the criterion judge."""

    selector: GraderSelector
    specs: list[GraderSpec] = field(default_factory=library_catalogue)
    degraded: bool = False  # a call failed at least once this run

    def __post_init__(self) -> None:
        self.specs = [s for s in self.specs if not s.uses_criterion_description]

    def match(self, criterion: Criterion, behaviour: Behaviour | None = None) -> str:
        return self.match_many([(criterion, behaviour)])[criterion.id]

    def match_many(
        self, pairs: Iterable[tuple[Criterion, Behaviour | None]]
    ) -> dict[str, str]:
        """The FQN for each Criterion ID, from one model call.

        Never raises. A Criterion with the criterion judge is a working Criterion, and an
        Interview that stops because the model call failed is not something the user can act on.
        """
        pairs = list(pairs)
        judged = {criterion.id: CRITERION_JUDGE_FQN for criterion, _ in pairs}
        # A grader with no Measure is not in the prompt, so it cannot be offered.
        offered = {
            spec.fqn
            for spec in self.specs
            if spec.taxonomy is not None and spec.taxonomy.measure is not None
        }
        if not pairs or not offered:
            return judged
        prompt = prompts.match_graders(
            self.specs,
            json.dumps(
                [
                    _criterion_payload(criterion, behaviour)
                    for criterion, behaviour in pairs
                ],
                ensure_ascii=False,
                indent=2,
            ),
        )
        try:
            choices = self.selector.select_graders(prompt, offered, set(judged))
        except Exception:
            # The user sees only a short warning, so the cause goes to the log.
            logger.warning("grader_matching_failed", exc_info=True)
            self.degraded = True
            return judged
        for choice in choices.choices:
            if choice.criterion_id in judged and choice.grader in offered:
                judged[choice.criterion_id] = choice.grader
        return judged


def match_specification(specification: Specification, matcher: GraderMatcher) -> int:
    """Match every Criterion without a grader in one call. Returns how many were matched.

    Existing graders and settings stay. Dormant Criteria also need a grader, because they stay
    in the shared document.
    """
    pairs = [
        (criterion, behaviour)
        for behaviour in specification.behaviours()
        for criterion in behaviour.criteria
        if not criterion.grader_fqn
    ]
    if not pairs:
        return 0
    fqns = matcher.match_many(pairs)
    for criterion, _ in pairs:
        criterion.grader_fqn = fqns[criterion.id]
        criterion.grader_args = default_grader_args(criterion)
    return len(pairs)


def rematch(criterion: Criterion, matcher: GraderMatcher) -> str:
    """Match one Criterion again after its text changed.

    The settings stay when the grader does not change. A new grader gets its default settings.
    """
    previous = criterion.grader_fqn
    criterion.grader_fqn = matcher.match(criterion)
    if previous != criterion.grader_fqn:
        criterion.grader_args = default_grader_args(criterion)
    return criterion.grader_fqn


def default_grader_args(criterion: Criterion) -> dict[str, Any]:
    if not criterion.grader_fqn:
        return {}
    module, name = criterion.grader_fqn.rsplit(".", 1)
    try:
        model = getattr(import_module(module), name).args_model
    except (ImportError, AttributeError):
        return {}
    return {
        name: info.get_default(call_default_factory=True)
        for name, info in model.model_fields.items()
        if not info.is_required()
        and not (name in {"model", "max_input_tokens"} and issubclass(model, JudgeArgs))
        # An unset taxonomy setting means the grader's own default, so it is not copied.
        and not (
            name in {"scope", "judgment_form", "aggregation"} and info.default is None
        )
    }


def validate_grader_args(
    fqn: str | None, args: Any, *, description: str | None = None
) -> None:
    """Check ``args`` against the grader's ``args_model``, as the engine will before a run.

    A model-based grader's ``model`` is filled in with a placeholder when absent: the engine
    resolves it at run time, so its absence here is not an error.
    """
    if not fqn or not isinstance(args, dict):
        raise ValueError("Select a Grader and supply a JSON object.")
    try:
        module, name = fqn.rsplit(".", 1)
        cls = getattr(import_module(module), name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if not (isinstance(cls, type) and issubclass(cls, Grader)):
        raise ValueError(f"{fqn} is not a metis.library.grader.Grader")
    # The same check as the engine's `resolve_grader_class`, repeated here because the
    # wizard must not import the engine.
    if inspect.isabstract(cls) or not hasattr(cls, "args_model"):
        raise ValueError(f"{fqn} is an abstract base, not a concrete grader")
    candidate = criterion_judge_args(cls.args_model, args, description)
    if issubclass(cls.args_model, JudgeArgs):
        candidate.setdefault("model", "resolved-at-run-time")
    try:
        cls.args_model.model_validate(candidate)
    except ValidationError as exc:
        raise ValueError(
            "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        ) from exc
