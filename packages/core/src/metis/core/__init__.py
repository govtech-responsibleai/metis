"""metis.core — Domain models, interfaces, and infrastructure."""

from importlib.metadata import PackageNotFoundError, version

from metis.core.artifacts import Artifact, resolve_artifact_path
from metis.core.console import console
from metis.core.logging import configure_logging, get_logger
from metis.core.model_settings import ModelRole, load_env, resolve_role
from metis.core.models import Status
from metis.core.traces import GradingInput, Observation, SessionTraces, Trace

try:
    __version__ = version("metis-core")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = [
    "Artifact",
    "GradingInput",
    "ModelRole",
    "Observation",
    "SessionTraces",
    "Status",
    "Trace",
    "__version__",
    "configure_logging",
    "console",
    "get_logger",
    "load_env",
    "resolve_artifact_path",
    "resolve_role",
]
