"""metis.insights — Report generation for METIS evaluation results."""

from importlib.metadata import PackageNotFoundError, version

from metis.insights._report import build_report, load_report_sources
from metis.insights.report import (
    ReportBuildError,
    ReportFiles,
    ResultsMissing,
    ensure_report,
    format_terminal_summary,
    save_report,
)

try:
    __version__ = version("metis-insights")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = [
    "ReportFiles",
    "ResultsMissing",
    "ReportBuildError",
    "__version__",
    "build_report",
    "ensure_report",
    "format_terminal_summary",
    "load_report_sources",
    "save_report",
]
