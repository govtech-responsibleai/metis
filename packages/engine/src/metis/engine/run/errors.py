"""The errors that the run functions raise in place of an exit.

Each error's text has already been printed to the run's console when it is raised. ``str()``
of a ``RunError`` is the reason that a ``failed`` phase line records.
"""

from __future__ import annotations


class RunError(RuntimeError):
    """A run step failed. The CLI exits with code 1."""


class InvalidInputsError(RunError):
    """The input folder of a new run is not valid."""


class ExperimentExistsError(RunError):
    """The experiment folder name of a new run is already used."""


class EvaluationInputError(RunError):
    """An experiment folder, its snapshot, or one of its trial records is not valid."""


class RunStopped(RuntimeError):
    """The caller's stop flag ended the run. The CLI exits with code 130.

    It is not a ``RunError``, so code that handles a failure never treats a stop as one.
    """


__all__ = [
    "EvaluationInputError",
    "ExperimentExistsError",
    "InvalidInputsError",
    "RunError",
    "RunStopped",
]
