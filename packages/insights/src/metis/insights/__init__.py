"""metis.insights — Report generation for METIS evaluation results."""

from importlib.metadata import PackageNotFoundError, version

from metis.insights._models import Report
from metis.insights._report import build_report, load_report_sources
from metis.insights.report import format_terminal_summary, save_report

try:
    __version__ = version("metis-insights")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = [
    "Report",
    "__version__",
    "build_report",
    "format_terminal_summary",
    "load_report_sources",
    "save_report",
]
