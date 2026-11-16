"""The error that a route raises to give a failure in the service error shape.

`main.py` maps each `RouteError` to a `ServiceError` body with its status, so a route can stop
at any depth with one `raise`.
"""

from __future__ import annotations


class RouteError(Exception):
    """A request that a route refuses. The app maps it to the service error shape."""

    def __init__(
        self, status: int, code: str, message: str, *, retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


__all__ = ["RouteError"]
