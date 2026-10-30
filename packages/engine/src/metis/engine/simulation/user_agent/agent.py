"""The user agent: one plain-language action per turn, from the persona and scenario."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from openai import APIError, AsyncOpenAI

from metis.core.logging import get_logger

from ..exceptions import UserAgentUnavailableError
from ..llm_calls import is_retryable, parse_completion
from ..model_settings import llm_client, sampling_options, user_agent_settings
from ..types import UserAgentOutput
from ..user_context import persona_text, scenario_text
from .prompts import FIRST_TURN, OBSERVATION, STATE, SYSTEM_PROMPT

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

    from metis.core import Artifact
    from metis.core.model_settings import RoleSettings

    from ..llm_calls import LLMCallLog
    from ..types import Observation, Persona, Promise, Scenario

logger = get_logger()

HISTORY_TURNS = 20
"""How many earlier turns the model is shown."""


def _file_line(artifact: Artifact) -> str:
    """The file as its facts line, which code wrote. Never its content."""
    return f"- {artifact.content_description or artifact.name}"


def render_files(held: list[Artifact]) -> str:
    """The files the user holds, in two groups so its own uploads are not mistaken for
    deliveries. Only received files are listed, so a failed download never appears."""
    sent = [a for a in held if a.source == "fixture"]
    received = [a for a in held if a.source != "fixture" and a.state == "received"]
    lines: list[str] = []
    if sent:
        lines.append("Files you have to send (your own):")
        lines.extend(_file_line(a) for a in sent)
    if received:
        lines.append("Files you received from the assistant:")
        lines.extend(_file_line(a) for a in received)
    return "\n".join(lines) or "none"


def render_observation(observation: Observation) -> str:
    """What came back: the reply as code copied it, then the runner's reading, labelled."""
    reply = observation.reply
    notice = f"{observation.notice}\n" if observation.notice else ""
    if not observation.observed:
        notice += "Nobody could check the assistant's state after this action.\n"
    reading = observation.reading
    return OBSERVATION.format(
        reply="(no reply was shown)" if reply is None else reply,
        notice=notice,
        outcome=reading.outcome,
        why=reading.why,
        next_options=(
            f"- what you could do next: {reading.next_options}\n"
            if reading.next_options
            else ""
        ),
    )


class UserAgent:
    """Plays one persona against one scenario, a turn at a time."""

    def __init__(
        self,
        persona: Persona,
        scenario: Scenario,
        *,
        llm_log: LLMCallLog,
        client: AsyncOpenAI | None = None,
        settings: RoleSettings | None = None,
    ) -> None:
        """
        :param llm_log: The trial's LLM-call log; every attempt at every call appends a row.
        :param client: Replaces the default client. It must have ``max_retries=0``,
            because retries happen in ``parse_completion`` where each one is logged.
        :param settings: The user agent role. Unset, it resolves from the environment.
        """
        self._llm_log = llm_log
        self.settings = settings or user_agent_settings()
        self._client = client or llm_client(self.settings)
        self._system = SYSTEM_PROMPT.format(
            persona_description=persona_text(persona.description, persona.metadata),
            scenario_description=scenario_text(scenario.description, scenario.metadata),
        )
        self._history: list[tuple[UserAgentOutput, Observation]] = []

    async def decide(
        self, turn: int, held: list[Artifact], promised: list[Promise]
    ) -> UserAgentOutput:
        """Choose the next action.

        :param held: Every file the user holds now; each is shown as its facts line.
        :param promised: Files the target promised and has not delivered.
        """
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": self._system}
        ]
        for said, came_back in self._history[-HISTORY_TURNS:]:
            # The reasoning stays out: it was private the first time.
            action = {"action": said.action, "decision": said.decision}
            messages.append(
                {"role": "assistant", "content": json.dumps(action, ensure_ascii=False)}
            )
            messages.append({"role": "user", "content": render_observation(came_back)})
        state = STATE.format(
            turn=turn,
            files=render_files(held),
            promised="\n".join(
                f"- {p.name} (promised in turn {p.turn})" for p in promised
            )
            or "none",
        )
        # The state goes in the final user message, after the last reply if there is one.
        if self._history:
            last_reply = render_observation(self._history[-1][1])
            messages[-1] = {"role": "user", "content": f"{last_reply}\n{state}"}
        else:
            messages.append({"role": "user", "content": f"{FIRST_TURN}\n\n{state}"})
        output = await self._call(messages)
        logger.info(
            "user_agent_decided",
            turn=turn,
            decision=output.decision,
            action=output.action,
            reasoning=output.reasoning,
        )
        return output

    def remember(self, output: UserAgentOutput, observation: Observation) -> None:
        """Record what was done and what came back, for the next turn's history."""
        self._history.append((output, observation))

    async def _call(
        self, messages: list[ChatCompletionMessageParam]
    ) -> UserAgentOutput:
        options = sampling_options()
        try:
            response = await parse_completion(
                self._client,
                self._llm_log,
                component="user_agent",
                model=self.settings.model,
                messages=messages,
                response_format=UserAgentOutput,
                **options,
            )
        except APIError as exc:
            if is_retryable(exc):
                raise UserAgentUnavailableError(
                    f"User agent LLM unavailable: {exc}"
                ) from exc
            raise RuntimeError(f"User agent LLM call failed: {exc}") from exc
        message = response.choices[0].message
        if message.parsed is not None:
            return message.parsed
        if message.refusal:
            raise RuntimeError(f"User agent LLM refused: {message.refusal}")
        raise RuntimeError(
            "User agent LLM returned an unparseable response "
            f"(finish_reason={response.choices[0].finish_reason})"
        )
