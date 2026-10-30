"""Shared wording for the evaluation trial count."""

from __future__ import annotations


def format_trials(count: int) -> str:
    """State a trial count with the correct singular or plural unit."""
    return f"{count} trial" if count == 1 else f"{count} trials"
