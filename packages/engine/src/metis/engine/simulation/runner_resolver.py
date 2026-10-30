"""Dynamic resolution of RunnerFactory classes from FQN strings."""

from __future__ import annotations

import importlib


def resolve_runner_factory(fqn: str) -> type:
    """Import and validate a RunnerFactory class from a fully-qualified name.

    Args:
        fqn: Dotted path like 'metis.engine.simulation.runners.http.HttpRunnerFactory'

    Returns:
        The class object (not an instance).

    Raises:
        ValueError: If fqn has no dot separator.
        ImportError: If the module or attribute cannot be found.
        TypeError: If the resolved object does not satisfy RunnerFactory.
    """
    if "." not in fqn:
        raise ValueError(
            f"runner_factory_ref must be a dotted fully-qualified name, got: {fqn!r}"
        )

    module_path, class_name = fqn.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ImportError(str(exc)) from exc

    if not hasattr(module, class_name):
        raise ImportError(f"Module {module_path!r} has no attribute {class_name!r}")

    cls = getattr(module, class_name)

    required_methods = ("start", "create", "close")
    missing = [m for m in required_methods if not callable(getattr(cls, m, None))]
    if missing:
        raise TypeError(
            f"{fqn} does not satisfy the RunnerFactory protocol "
            f"(missing: {', '.join(missing)})"
        )

    return cls
