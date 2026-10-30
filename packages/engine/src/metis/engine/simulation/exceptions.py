"""Typed exception hierarchy for simulation resilience layers.

Hierarchy:
    SimulationError (base — never raised directly)
    ├── TurnRecoverableError (caught by turn layer)
    ├── TrialRecoverableError (caught by trial layer)
    │   ├── ConsecutiveFailureEscalation
    │   └── UserAgentUnavailableError
    ├── ResponseTimeoutError (record incomplete, continue)
    └── TargetSessionEnded (clean stop, target exhausted)

A runner raises ``TurnRecoverableError`` or ``TrialRecoverableError`` itself, or a subclass of
either, to say how far the failure reaches.
"""


class SimulationError(Exception):
    pass


class TurnRecoverableError(SimulationError):
    pass


class TrialRecoverableError(SimulationError):
    pass


class ConsecutiveFailureEscalation(TrialRecoverableError):
    pass


class UserAgentUnavailableError(TrialRecoverableError):
    """The persona LLM kept failing with a transient error past the call's own retries.

    The endpoint, not the trial, is at fault, so the experiment replays the trial.
    A permanent failure (bad key, bad request, refusal, unparseable output) is not
    this error: it stays a ``system_error``.
    """


class ResponseTimeoutError(SimulationError):
    pass


class TargetSessionEnded(SimulationError):
    """The session cannot carry another turn, whatever the persona sends.

    Not the target refusing one message but the session itself being spent —
    a lifetime budget reached, or an input cap that the accumulated context
    keeps exceeding.

    Neither turn- nor run-recoverable: retrying the turn cannot succeed and a
    fresh session would not continue the same conversation. The orchestrator
    ends the run with stop reason target_exhausted and a clean record.
    """
