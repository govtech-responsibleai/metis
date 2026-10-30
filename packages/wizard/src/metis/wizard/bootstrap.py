"""Production composition root for the wizard.

This is the only module that assembles more than one adapter. Shared application code and the
CLI adapter depend on protocols; this module supplies the LLM gateway implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.wizard.adapters.cli import commands
from metis.wizard.adapters.llm.gateway import GatewayInterviewer

if TYPE_CHECKING:
    from collections.abc import Callable

    import typer

    from metis.core.model_settings import RoleSettings
    from metis.wizard.application.interviewer import Interviewer


def platform_interviewer(interview_id: str | None = None) -> Interviewer:
    """Construct the real gateway-backed interviewer for one CLI run."""
    return GatewayInterviewer(interview_id=interview_id)


def configure_interview_runtime(*, interview: RoleSettings) -> None:
    """Install the production Interviewer and matcher used by the public Interview function.

    Provider construction stays in this composition root. Callers give the resolved settings of
    the interview role (`metis.core.model_settings.resolve_role`) and never need to import or
    operate the gateway, matcher, or driver objects. The settings stay in the objects. This
    function does not write them to the environment.
    """
    from metis.wizard.application.matching import GraderMatcher
    from metis.wizard.application.turn import configure_interview_dependencies

    interviewer = GatewayInterviewer(interview=interview)
    configure_interview_dependencies(interviewer, GraderMatcher(selector=interviewer))


def create_cli_app(
    interviewer_factory: Callable[..., Interviewer] = platform_interviewer,
) -> typer.Typer:
    """Compose the CLI with an interviewer provider.

    The optional factory is the test seam: the same Typer app and terminal loop can be driven
    with a deterministic provider without importing or calling the network gateway.
    """
    commands.configure(interviewer_factory=interviewer_factory)
    return commands.app


cli_app = create_cli_app()


__all__ = [
    "cli_app",
    "configure_interview_runtime",
    "create_cli_app",
    "platform_interviewer",
]
