"""A gateway whose raw model replies are scripted.

The real retry loop, patch review and correction run on these replies, with no network. A test
of the reply rule drives the driver with this gateway, so it sees each attempt as the user's
turn would.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metis.wizard.adapters.llm.gateway import GatewayInterviewer


@dataclass
class FakeCompletions:
    """Returns a scripted sequence of raw strings, recording what it was sent.

    After the last reply, the last one repeats.
    """

    replies: list[str]
    calls: list[dict] = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]

        class Message:
            content = text

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        return Response()


@dataclass
class FakeClient:
    completions: FakeCompletions

    @property
    def chat(self):
        return self


def scripted_gateway(replies: list[str]) -> tuple[GatewayInterviewer, FakeCompletions]:
    completions = FakeCompletions(replies=replies)
    return GatewayInterviewer(_client=FakeClient(completions=completions)), completions
