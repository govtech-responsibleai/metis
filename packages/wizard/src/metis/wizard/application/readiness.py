"""The shared Specification-readiness rules.

Stage derivation, the Scenario and Test Case gates, best-effort finish and compile preflight all
ask about the same Specification. The complete collector owns the objective gaps; the Scenario
helper owns the engine-facing Scenario and Test Case rules. Keeping both here stops the application from growing several
slightly different definitions of "ready".

The result is a list of `MissingData` — the same structured shape a turn returns to a caller —
so a door can render the gaps and finish can report them without re-deriving anything. An empty
list means ready.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.wizard.contracts.turn import MissingData, MissingDataCode
from metis.wizard.domain.nodes import duplicate_test_cases
from metis.wizard.domain.permissions import InterviewStep

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

    from metis.wizard.domain.specification import Specification

# The engine schema bounds a scenario's trial count; the Test Case screen's stepper enforces the
# same range door-side. Kept here so the screen and the readiness check cannot disagree on it.
TRIALS_MIN = 1
TRIALS_MAX = 20


def missing_criteria_paths(specification: Specification) -> frozenset[str]:
    """The writable Criteria collections for measured Behaviours with no Criteria."""
    return frozenset(
        f"features[{feature.id}].behaviours[{behaviour.id}].criteria"
        for feature in specification.features
        for behaviour in feature.behaviours
        if behaviour.measured and not behaviour.criteria
    )


def scenario_readiness(
    specification: Specification, excluded: AbstractSet[str] = frozenset()
) -> list[MissingData]:
    """Every reason the Scenarios and selected Test Cases are not yet runnable, in order.

    A missing Scenario is a gap of the Scenario review. Every other gap belongs to the Test
    Case review. `excluded` holds the Test Cases that the user cleared. They do not run, so
    they neither cover a Behaviour nor block Continue with their own faults. An empty list
    means the Specification passes both gates.
    """
    gaps: list[MissingData] = []

    if not specification.scenarios:
        gaps.append(
            _gap(
                MissingDataCode.NO_SCENARIOS,
                None,
                "There are no scenarios yet.",
                stage=InterviewStep.SCENARIOS,
            )
        )
        return gaps

    tasks = [task for task in specification.tasks if task.id not in excluded]
    if not tasks:
        gaps.append(
            _gap(
                MissingDataCode.NO_SELECTED_TEST_CASE,
                None,
                "Select at least one Test Case.",
            )
        )
        return gaps

    persona_ids = {persona.id for persona in specification.personas}
    measured = {b.id for b in specification.measured_behaviours()}

    # A measured behaviour no selected Test Case exercises is measured on nothing.
    covered = {
        ref
        for task in tasks
        if task.persona_ref in persona_ids and specification.scenario(task.scenario_ref)
        for ref in task.behaviour_refs
    }
    for behaviour in specification.measured_behaviours():
        if behaviour.id not in covered:
            gaps.append(
                _gap(
                    MissingDataCode.BEHAVIOUR_UNCOVERED,
                    behaviour.id,
                    f"{behaviour.id} is covered by no selected Test Case.",
                )
            )

    for later, earlier in duplicate_test_cases(specification, tasks):
        gaps.append(
            _gap(
                MissingDataCode.SCENARIO_DUPLICATE_PAIR,
                later,
                f"{later} uses the same Persona and Scenario as {earlier}.",
            )
        )
    for task in tasks:
        if not task.behaviour_refs or not set(task.behaviour_refs) <= measured:
            gaps.append(
                _gap(
                    MissingDataCode.SCENARIO_NO_SELECTED_BEHAVIOUR,
                    task.id,
                    f"{task.id} needs measured Behaviours.",
                )
            )
        if (
            task.persona_ref not in persona_ids
            or not specification.scenario(task.scenario_ref)
            or any(specification.behaviour(ref) is None for ref in task.behaviour_refs)
        ):
            gaps.append(
                _gap(
                    MissingDataCode.SCENARIO_UNKNOWN_REFERENCE,
                    task.id,
                    f"{task.id} has an unknown reference.",
                )
            )
        if not TRIALS_MIN <= task.num_trials <= TRIALS_MAX:
            gaps.append(
                _gap(
                    MissingDataCode.SCENARIO_INVALID_TRIALS,
                    task.id,
                    f"{task.id} needs between 1 and 20 Trials.",
                )
            )

    return gaps


def specification_readiness(
    specification: Specification, excluded: AbstractSet[str] = frozenset()
) -> list[MissingData]:
    """Return all objective gaps before a Specification can produce a runnable experiment."""
    gaps: list[MissingData] = []
    if not specification.target.name or not specification.target.description:
        gaps.append(
            MissingData(
                code=MissingDataCode.TARGET_INCOMPLETE,
                stage=InterviewStep.CLARIFY,
                message="The target name and description are required.",
            )
        )

    if not specification.features or not specification.behaviours():
        gaps.append(
            MissingData(
                code=MissingDataCode.BEHAVIOURS_INCOMPLETE,
                stage=InterviewStep.BEHAVIOURS,
                message="At least one Feature and Behaviour are required.",
            )
        )
    elif not specification.measured_behaviours():
        gaps.append(
            MissingData(
                code=MissingDataCode.NO_MEASURED_BEHAVIOUR,
                stage=InterviewStep.BEHAVIOURS,
                message="At least one Behaviour must be measured.",
            )
        )

    for behaviour in specification.measured_behaviours():
        if not behaviour.criteria:
            gaps.append(
                MissingData(
                    code=MissingDataCode.CRITERIA_INCOMPLETE,
                    stage=InterviewStep.CRITERIA,
                    subject=behaviour.id,
                    message=f"{behaviour.id} needs at least one Criterion.",
                )
            )

    if not specification.personas:
        gaps.append(
            MissingData(
                code=MissingDataCode.NO_PERSONAS,
                stage=InterviewStep.PERSONAS,
                message="At least one Persona is required.",
            )
        )

    gaps.extend(scenario_readiness(specification, excluded))
    return gaps


def _gap(
    code: MissingDataCode,
    subject: str | None,
    message: str,
    *,
    stage: InterviewStep = InterviewStep.TEST_CASES,
) -> MissingData:
    return MissingData(
        code=code,
        stage=stage,
        subject=subject,
        message=message,
    )


def selected_specification(
    specification: Specification, excluded: AbstractSet[str]
) -> Specification:
    """A copy with only the selected Test Cases: what compile and export use.

    A Scenario that no selected Test Case uses is left out too, because the engine runs each
    Scenario through its Test Cases.
    """
    copy = specification.model_copy(deep=True)
    copy.tasks = [task for task in copy.tasks if task.id not in excluded]
    used = {task.scenario_ref for task in copy.tasks}
    copy.scenarios = [scenario for scenario in copy.scenarios if scenario.id in used]
    return copy
