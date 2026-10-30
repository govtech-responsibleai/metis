"""Criterion → grader: the model-call matcher, and the checks on a Criterion's grader."""

from __future__ import annotations

import pytest

from metis.library.graders.demo import DemoTraceBudgetGrader
from metis.wizard.application.compile import CompilationError, compile_experiment
from metis.wizard.application.matching import (
    CRITERION_JUDGE_FQN,
    GraderMatcher,
    match_specification,
    rematch,
)
from metis.wizard.application.matching.matcher import (
    check_grader_choices,
    validate_grader_args,
)
from metis.wizard.contracts import Criterion, GraderSpec
from metis.wizard.contracts.output import GraderChoice, GraderChoices
from tests.fixtures.wizard.specifications import research_assistant

TRACE_BUDGET = "metis.library.graders.demo.DemoTraceBudgetGrader"
BUDGET = GraderSpec(
    fqn=TRACE_BUDGET,
    name="Trace budget sentinel",
    description="TRACE BUDGET SENTINEL SUMMARY",
    taxonomy=DemoTraceBudgetGrader.taxonomy,
)
JUDGE = GraderSpec(
    fqn=CRITERION_JUDGE_FQN,
    name="Criterion judge",
    description="Any criterion.",
    uses_criterion_description=True,
)


class FakeSelector:
    """Returns the scripted grader for each Criterion ID and records each call."""

    def __init__(self, picks: dict[str, str | None], *, fails: bool = False) -> None:
        self.picks = picks
        self.fails = fails
        self.calls: list[tuple[str, set[str], set[str]]] = []

    def select_graders(self, prompt, offered, criterion_ids) -> GraderChoices:
        self.calls.append((prompt.user, offered, criterion_ids))
        if self.fails:
            raise RuntimeError("model call failed")
        return GraderChoices(
            choices=[
                GraderChoice(criterion_id=id, grader=self.picks.get(id))
                for id in criterion_ids
            ]
        )


def _unmatched_specification():
    specification = research_assistant()
    for behaviour in specification.behaviours():
        for criterion in behaviour.criteria:
            criterion.grader_fqn = None
            criterion.grader_args = {}
    return specification


def _criteria(specification) -> list[Criterion]:
    return [c for b in specification.behaviours() for c in b.criteria]


# ── matching ───────────────────────────────────────────────────────────────


def test_one_call_matches_every_unmatched_criterion_with_its_suggestion() -> None:
    specification = _unmatched_specification()
    first, *others = _criteria(specification)
    selector = FakeSelector({first.id: TRACE_BUDGET})
    matcher = GraderMatcher(selector=selector, specs=[JUDGE, BUDGET])

    matched = match_specification(specification, matcher)

    assert matched == 1 + len(others)
    [(user, offered, ids)] = selector.calls
    assert offered == {TRACE_BUDGET}  # the criterion judge is never offered
    assert ids == {c.id for c in _criteria(specification)}
    assert BUDGET.description in user
    assert str(first.description) in user
    assert first.grader_fqn == TRACE_BUDGET
    assert first.grader_args == {"threshold": 0.5, "max_traces": 10}
    assert {c.grader_fqn for c in others} == {CRITERION_JUDGE_FQN}
    assert not matcher.degraded


def test_existing_graders_are_kept_and_cost_no_call() -> None:
    specification = research_assistant()
    selector = FakeSelector({})

    assert (
        match_specification(specification, GraderMatcher(selector, specs=[BUDGET])) == 0
    )
    assert selector.calls == []


@pytest.mark.parametrize(
    ("selector", "degraded"),
    [
        (FakeSelector({"AC-1-1": "not.an.Offered"}), False),
        (FakeSelector({"AC-1-1": TRACE_BUDGET}, fails=True), True),
    ],
)
def test_an_unknown_grader_or_a_failed_call_gives_the_criterion_judge(
    selector: FakeSelector, degraded: bool
) -> None:
    criterion = Criterion(
        id="AC-1-1", name="Criterion", description="It cites sources."
    )
    matcher = GraderMatcher(selector=selector, specs=[BUDGET])

    assert matcher.match(criterion) == CRITERION_JUDGE_FQN
    assert matcher.degraded is degraded


def test_with_no_library_grader_the_judge_is_chosen_without_a_call() -> None:
    selector = FakeSelector({}, fails=True)
    matcher = GraderMatcher(selector=selector, specs=[JUDGE])

    criterion = Criterion(
        id="AC-1-1", name="Criterion", description="It cites sources."
    )

    assert matcher.match(criterion) == CRITERION_JUDGE_FQN
    assert selector.calls == []
    assert not matcher.degraded


def test_rematch_keeps_settings_for_the_same_grader_and_resets_them_for_a_new_one() -> (
    None
):
    criterion = Criterion(
        id="AC-1-1",
        name="Criterion",
        description="It names a source.",
        grader_fqn=CRITERION_JUDGE_FQN,
        grader_args={"model": "chosen-judge", "threshold": 0.8},
    )

    rematch(criterion, GraderMatcher(FakeSelector({}), specs=[BUDGET]))
    assert criterion.grader_args == {"model": "chosen-judge", "threshold": 0.8}

    rematch(
        criterion, GraderMatcher(FakeSelector({"AC-1-1": TRACE_BUDGET}), specs=[BUDGET])
    )
    assert criterion.grader_fqn == TRACE_BUDGET
    assert criterion.grader_args == {"threshold": 0.5, "max_traces": 10}


@pytest.mark.parametrize(
    ("choices", "named"),
    [
        ([GraderChoice(criterion_id="AC-1-1", grader="not.Offered")], "not.Offered"),
        ([], "AC-1-1"),
        (
            [
                GraderChoice(criterion_id="AC-1-1", grader=None),
                GraderChoice(criterion_id="AC-9-9", grader=None),
            ],
            "AC-9-9",
        ),
    ],
)
def test_a_reply_outside_the_request_is_rejected(
    choices: list[GraderChoice], named: str
) -> None:
    with pytest.raises(ValueError, match=named):
        check_grader_choices(GraderChoices(choices=choices), {TRACE_BUDGET}, {"AC-1-1"})


def test_a_reply_without_a_grader_means_no_library_grader() -> None:
    choices = GraderChoices.model_validate_json(
        '{"choices": [{"criterion_id": "AC-1-1"}]}'
    )

    check_grader_choices(choices, {TRACE_BUDGET}, {"AC-1-1"})
    assert choices.choices[0].grader is None


# ── grader settings ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args", [{"criterion": "override"}, {"unknown": 1}, {"threshold": 2}]
)
def test_compile_reports_invalid_fallback_settings_by_criterion(args) -> None:
    specification = research_assistant()
    criterion = specification.features[0].behaviours[0].criteria[0]
    criterion.grader_fqn = CRITERION_JUDGE_FQN
    criterion.grader_args = args
    with pytest.raises(CompilationError, match=criterion.id):
        compile_experiment(specification, "fallback")


def test_fallback_validation_uses_the_description_without_storing_instructions() -> (
    None
):
    specification = research_assistant()
    criterion = specification.features[0].behaviours[0].criteria[0]
    criterion.grader_fqn = CRITERION_JUDGE_FQN
    criterion.grader_args = {"threshold": 0.75}
    validate_grader_args(
        criterion.grader_fqn, criterion.grader_args, description=criterion.description
    )
    assert criterion.grader_args == {"threshold": 0.75}


def test_the_abstract_grader_base_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="abstract base"):
        validate_grader_args("metis.library.grader.Grader", {})


def test_a_concrete_grader_with_valid_args_passes() -> None:
    validate_grader_args(
        "tests.unit.engine.graders_for_tests.FixedScoreGrader", {"score": 1.0}
    )
