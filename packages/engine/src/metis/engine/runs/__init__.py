"""Run ``simulate`` and ``evaluate`` from Python, with no CLI.

The functions here do no terminal or process work. They never exit, never set a signal
handler, and write text only to the ``console`` that the caller gives. The caller sets up
the process before it calls one: it loads ``.env``, registers the METIS-internal Langfuse
client (``metis.engine.tracing.tracing_key``), and sets up process logging.

Only one run at a time is safe in one process. Logging, the Langfuse clients, and
``LANGFUSE_HOST`` in ``os.environ`` are shared by the whole process.
"""

from metis.engine.runs._inputs import (
    prepare_experiment,
    resolve_experiment_dir,
    validate_inputs,
)
from metis.engine.runs._simulation import resume_simulation, simulate
from metis.engine.runs.errors import (
    EvaluationInputError,
    ExperimentExistsError,
    InvalidInputsError,
    RunError,
    RunStopped,
)

__all__ = [
    "EvaluationInputError",
    "ExperimentExistsError",
    "InvalidInputsError",
    "RunError",
    "RunStopped",
    "prepare_experiment",
    "resolve_experiment_dir",
    "resume_simulation",
    "simulate",
    "validate_inputs",
]
