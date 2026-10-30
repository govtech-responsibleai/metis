"""Simulation-level configuration shared by every transport."""

from __future__ import annotations

from pydantic import BaseModel


class TrialRetryConfig(BaseModel):
    """Trial-level retry budget consumed by the experiment runner.

    A trial that fails with a TrialRecoverableError is torn down and retried
    from scratch up to trial_max_retries times, pausing trial_retry_delay_seconds
    between attempts.
    """

    trial_max_retries: int = 2
    trial_retry_delay_seconds: float = 5.0
