"""metis.engine: evaluation engine for METIS."""

from importlib.metadata import PackageNotFoundError, version

from metis.engine.evaluation import build_grader, grade_session
from metis.engine.extractor import fetch_session, get_langfuse_client

try:
    __version__ = version("metis-engine")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = [
    "__version__",
    "build_grader",
    "fetch_session",
    "get_langfuse_client",
    "grade_session",
]
