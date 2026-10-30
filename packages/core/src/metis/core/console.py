"""Shared Rich console for user-facing CLI output.

All packages use this instance for consistent terminal behavior
(color detection, width). Writes to stdout — separate from the
logging module's stderr console.
"""

from rich.console import Console

console = Console()
