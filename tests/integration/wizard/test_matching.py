"""The grader catalogue that the matcher and the prompts read from the library."""

import pytest

from metis.wizard.application.matching import CRITERION_JUDGE_FQN, library_catalogue

# ── the catalogue ──────────────────────────────────────────────────────────


def test_the_catalogue_lists_the_criterion_judge() -> None:
    library_catalogue.cache_clear()
    assert CRITERION_JUDGE_FQN in [spec.fqn for spec in library_catalogue()]


def test_the_catalogue_reads_an_exported_grader(a_catalogued_grader: type) -> None:
    specs = library_catalogue()

    fqns = [spec.fqn for spec in specs]
    assert CRITERION_JUDGE_FQN in fqns
    assert "metis.library.graders.DemoTraceBudgetGrader" in fqns
    assert fqns == sorted(fqns)
    assert all(spec.fqn and spec.name and spec.description for spec in specs)


def test_the_catalogue_covers_every_exported_grader() -> None:
    """The reader must find the whole library: every concrete Grader the package exports."""
    import inspect

    import metis.library.graders as graders
    from metis.library.grader import Grader

    exported = {
        name
        for name, obj in vars(graders).items()
        if inspect.isclass(obj)
        and issubclass(obj, Grader)
        and not inspect.isabstract(obj)
        and obj.__module__.startswith("metis.library.graders")
    }
    catalogued = {spec.fqn.rsplit(".", 1)[-1] for spec in library_catalogue()}
    assert catalogued == exported
    assert "Grader" not in catalogued  # the contract is not a choice


def test_the_catalogue_never_instantiates_a_grader(
    monkeypatch: pytest.MonkeyPatch, a_catalogued_grader: type
) -> None:
    """Parameters come from args_model; reading them must not build a grader."""

    def explode(*_a, **_kw):
        raise AssertionError("the catalogue instantiated a grader")

    monkeypatch.setattr(a_catalogued_grader, "__init__", explode)

    library_catalogue.cache_clear()
    assert library_catalogue()


def test_catalogue_params_come_from_args_model(a_catalogued_grader: type) -> None:
    spec = next(
        spec
        for spec in library_catalogue()
        if spec.fqn == "metis.library.graders.DemoTraceBudgetGrader"
    )
    assert [(p.name, p.type, p.default, p.required) for p in spec.params] == [
        ("threshold", "float", 0.5, False),
        ("max_traces", "int", 10, False),
    ]


def test_every_catalogued_fqn_is_importable() -> None:
    import importlib

    for spec in library_catalogue():
        module_path, _, class_name = spec.fqn.rpartition(".")
        assert hasattr(importlib.import_module(module_path), class_name), spec.fqn


def test_the_criterion_judge_has_only_configurable_parameters() -> None:
    fallback = next(
        spec for spec in library_catalogue() if spec.fqn == CRITERION_JUDGE_FQN
    )
    assert [param.name for param in fallback.params] == ["threshold"]
