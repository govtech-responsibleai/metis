"""The real interviewer, over the LLM gateway.

The gateway is OpenAI-compatible, so the client is `OpenAI` with a `base_url`. The interview role
(`metis.core.model_settings`) has its own model, key and URL, and falls back to the shared
`OPENAI_API_KEY` and `OPENAI_BASE_URL`. Grader matching is one more structured call on the same
client.

The client is imported from `langfuse.openai`, Langfuse's drop-in for the OpenAI client.
Importing it patches the client so every chat call is recorded as a generation —
input, raw reply, model, token usage and latency — with no tracing code on the call path.
`_ask` opens one observation, so a call's three attempts nest under one trace named by the
Interview step. A caller that has an Interview ID can use it to group traces; the stateless
lifecycle normally records them ungrouped. The traces go to the METIS-internal Langfuse, which is
opt-in by the three `METIS_INTERNAL_LANGFUSE_*` variables. The `LANGFUSE_*` variables name the
target's Langfuse, which the engine reads, so the wizard never uses them: with an internal
variable missing, the gateway holds a disabled client and sends nothing. The client exports on a
background thread, so it never blocks or fails the Interview.

Every call asks for structured output and retries twice on a validation failure, feeding the
error back each time. Three attempts total, silent unless all three fail: a first-attempt
schema miss is common and recoverable, and asking the user about it makes them the retry loop.

A call that returns patches also goes through the patch review (`application.patch_review`),
the same function that the driver uses for the real apply. When the review does not accept
every patch, the model gets one correction that names each problem and its reason, and returns a
new reply and new patches. The last attempt is returned as it is, and the result records the
reasons of every problem that any attempt had. The driver uses them to tell the user what did
not change.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any, TypeVar

from langfuse import Langfuse, get_client
from openai import APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from metis.core.model_settings import (
    METIS_INTERNAL_LANGFUSE_VARS,
    ROLES,
    ModelRole,
    RoleSettings,
    find_env_file,
    format_missing_settings,
    resolve_role,
)
from metis.core.profile import CriterionDescription
from metis.library.grader import CriterionJudgeArgs, GraderArgs, JudgeArgs
from metis.wizard.application import prompts
from metis.wizard.application.interviewer import (
    InterviewContextBudgetError,
    InterviewerOutputError,
    InterviewerUnavailable,
)
from metis.wizard.application.patch_review import PatchScope, review_patches
from metis.wizard.application.readiness import missing_criteria_paths
from metis.wizard.contracts.output import (
    ClarifyResult,
    CriterionConfiguration,
    GraderChoices,
    StepResult,
)
from metis.wizard.domain.applier import PatchValueError
from metis.wizard.domain.patch import PatchOp

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from metis.wizard.application.patch_review import PatchProblem
    from metis.wizard.contracts.interview_state import (
        InterviewContext,
        InterviewMessage,
    )
    from metis.wizard.domain.permissions import PatchReason
    from metis.wizard.domain.specification import Criterion, Specification

ATTEMPTS = 3

_TRACING_OFF_KEY = "metis-internal-tracing-off"

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R", bound=StepResult)


def _strict_schema(node: Any) -> Any:
    """Return `node` in the form that strict structured output accepts.

    Strict providers such as Azure OpenAI require every property in `required`. A field with a
    default becomes required and nullable, and the model returns `null` to leave it unset.
    `_drop_defaulted_nulls` removes those nulls before validation, so Pydantic applies the default.
    A `$ref` cannot have sibling keywords, so a `$ref` that Pydantic gives a `description` moves
    into a one-branch `anyOf` that keeps the description.
    """
    if isinstance(node, list):
        return [_strict_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node and len(node) > 1:
        siblings = {key: value for key, value in node.items() if key != "$ref"}
        return _strict_schema({**siblings, "anyOf": [{"$ref": node["$ref"]}]})
    node = {key: _strict_schema(value) for key, value in node.items()}
    properties = node.get("properties")
    if isinstance(properties, dict):
        required = set(node.get("required", []))
        for name, prop in properties.items():
            if name not in required:
                prop = {key: value for key, value in prop.items() if key != "default"}
                if not _allows_null(prop):
                    prop = {"anyOf": [prop, {"type": "null"}]}
                properties[name] = prop
        node["required"] = list(properties)
    return node


def _allows_null(node: dict[str, Any]) -> bool:
    return node.get("type") == "null" or any(
        branch.get("type") == "null" for branch in node.get("anyOf", [])
    )


def _drop_defaulted_nulls(data: Any, node: dict[str, Any], defs: dict[str, Any]) -> Any:
    """Remove the nulls that `_strict_schema` lets the model send for defaulted fields."""
    if "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[-1]]
    if isinstance(data, list) and isinstance(node.get("items"), dict):
        return [_drop_defaulted_nulls(item, node["items"], defs) for item in data]
    if not isinstance(data, dict):
        return data
    if "properties" in node:
        required = set(node.get("required", []))
        return {
            key: _drop_defaulted_nulls(value, node["properties"].get(key, {}), defs)
            for key, value in data.items()
            if value is not None or key in required
        }
    for branch in node.get("anyOf", []):
        resolved = (
            defs[branch["$ref"].rsplit("/", 1)[-1]] if "$ref" in branch else branch
        )
        if set(data) <= set(resolved.get("properties", {})):
            return _drop_defaulted_nulls(data, resolved, defs)
    return data


class CredentialsMissing(InterviewerUnavailable):
    """The gateway is not configured. Raised before any call is attempted."""


class ModelOutputError(InterviewerOutputError):
    """Three attempts, all of them malformed."""


def check_credentials(
    command: str = "metis wizard",
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
    *,
    interview: RoleSettings | None = None,
) -> None:
    """Fail before any model call when the interview role has no API key.

    ``interview`` is the resolved interview role; without it, the role resolves from ``env``.
    The message names
    the variables, the `.env` file that was read, and the model guide. The base URL is optional,
    as in the engine.
    """
    env = os.environ if env is None else env
    settings = interview or resolve_role(ModelRole.INTERVIEW, env)
    if not settings.configured:
        missing = {settings.role: ROLES[settings.role].key_vars}
        path = env_file if env_file is not None else find_env_file(env=env)
        raise CredentialsMissing(format_missing_settings(command, missing, path))


def tracing_key(env: Mapping[str, str] | None = None) -> str:
    """Register the METIS-internal Langfuse client and return its public key.

    Every traced call names this key, so the drop-in and `@observe` use this client and no
    other. A client built without keys reads `LANGFUSE_*`, the target's project. So when an
    internal variable is missing, the client is a disabled one under a placeholder key.
    """
    env = os.environ if env is None else env
    public_key, secret_key, base_url = (
        env.get(name) for name in METIS_INTERNAL_LANGFUSE_VARS
    )
    if public_key and secret_key and base_url:
        Langfuse(public_key=public_key, secret_key=secret_key, base_url=base_url)
        return public_key
    Langfuse(
        public_key=_TRACING_OFF_KEY, secret_key=_TRACING_OFF_KEY, tracing_enabled=False
    )
    return _TRACING_OFF_KEY


def _client(settings: RoleSettings) -> Any:
    # The drop-in traces every call; unconfigured it is a quiet no-op. The OpenAI client
    # does not connect on construction, so this stays offline until a call is made.
    from langfuse.openai import OpenAI

    # The base URL is the full OpenAI-compatible endpoint; the client uses it as given.
    return OpenAI(
        base_url=settings.base_url.rstrip("/") if settings.base_url else None,
        api_key=settings.api_key,
    )


@dataclass
class GatewayInterviewer:
    """Structured-output calls against the gateway."""

    interview: RoleSettings = field(
        default_factory=lambda: resolve_role(ModelRole.INTERVIEW, os.environ)
    )
    context_tokens: int = field(
        default_factory=lambda: int(
            os.environ.get("INTERVIEW_CONTEXT_TOKENS", "128000")
        )
    )
    output_tokens: int = field(
        default_factory=lambda: int(os.environ.get("INTERVIEW_OUTPUT_TOKENS", "16384"))
    )
    _client: Any = None
    interview_id: str | None = None
    _tracing_key: str = field(default_factory=tracing_key)

    def __post_init__(self) -> None:
        if self._client is None:
            # A missing key costs no model call: the check runs before any client exists.
            check_credentials(interview=self.interview)
        if not 0 < self.output_tokens < self.context_tokens:
            raise ValueError(
                "INTERVIEW_OUTPUT_TOKENS must be positive and below INTERVIEW_CONTEXT_TOKENS."
            )
        if self._client is None:
            self._client = _client(self.interview)

    @property
    def model(self) -> str:
        """The interview model."""
        return self.interview.model

    # ── the retry loop ─────────────────────────────────────────────────────

    def _ask(
        self,
        prompt: prompts.ModelPrompt,
        schema: type[T],
        validate: Callable[[T], None] | None = None,
        review: Callable[[T], list[PatchProblem]] | None = None,
    ) -> tuple[T, bool]:
        """Ask once, validate, and retry twice with the error fed back.

        Silent unless all three fail. The caller then raises a RUNTIME warning and redraws
        the previous screen, so nothing already decided is lost.

        `review` returns the problems that the patch review found in a valid result. A result
        with problems gets one more attempt with the problems fed back, and the last attempt is
        returned with its problems.

        Returns the result and whether a retry was needed: a first-attempt success is `False`,
        anything that took a correction is `True`.

        The observation opens the trace; each attempt's `create` call nests under it as a
        generation. The trace is named by the interview step and, where known, carries the
        interview id, so one interview reads as one sequence. A call with no interview id is still
        recorded, ungrouped.
        """
        tracer = get_client(public_key=self._tracing_key)
        with tracer.start_as_current_observation(
            name=prompt.name, input={"system": prompt.system, "user": prompt.user}
        ) as observation:
            # `session_id=` is the Langfuse SDK's trace-grouping parameter. It stays empty when
            # a stateless caller has no Interview ID; the call is still traced.
            tracer.update_current_trace(name=prompt.name, session_id=self.interview_id)
            result, recovered = self._attempts(prompt, schema, validate, review)
            observation.update(output=result.model_dump(mode="json"))
            return result, recovered

    def _attempts(
        self,
        prompt: prompts.ModelPrompt,
        schema: type[T],
        validate: Callable[[T], None] | None,
        review: Callable[[T], list[PatchProblem]] | None,
    ) -> tuple[T, bool]:
        messages = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]
        last_error: Exception | None = None

        model_schema = schema.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": _strict_schema(model_schema),
                "strict": True,
            },
        }
        for attempt in range(ATTEMPTS):
            # One token per UTF-8 byte is a conservative bound for byte-based model
            # tokenizers. Include schema, retry history, framing, and reserved output.
            input_bound = (
                len(
                    json.dumps(
                        {"messages": messages, "response_format": response_format},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                + 4096
            )
            if input_bound + self.output_tokens > self.context_tokens:
                raise InterviewContextBudgetError(
                    f"Request for {self.model} needs a conservative budget of "
                    f"{input_bound + self.output_tokens:,} tokens; configured context is "
                    f"{self.context_tokens:,}. No input was truncated. Set INTERVIEW_CONTEXT_TOKENS "
                    "to the provider's supported limit or reduce the documents."
                )
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format=response_format,
                    max_completion_tokens=self.output_tokens,
                    langfuse_public_key=self._tracing_key,
                )
            except APIError as exc:
                raise InterviewerOutputError(
                    "The model gateway could not complete the request."
                ) from exc
            text = response.choices[0].message.content or ""

            try:
                result = schema.model_validate(
                    _drop_defaulted_nulls(
                        json.loads(text), model_schema, model_schema.get("$defs", {})
                    )
                )
                if validate is not None:
                    validate(result)
            except (ValidationError, PatchValueError, json.JSONDecodeError) as exc:
                last_error = exc
                correction = (
                    "That didn't validate against the schema:\n"
                    f"{exc}\n\nReturn corrected JSON only."
                )
            else:
                problems = review(result) if review is not None else []
                if not problems or attempt == ATTEMPTS - 1:
                    return result, attempt > 0
                correction = prompts.model_feedback(problems)
            if attempt < ATTEMPTS - 1:
                # Feed the failure back, so the next attempt is not a blind one.
                messages += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": correction},
                ]

        raise ModelOutputError(
            f"The model returned output I couldn't read, {ATTEMPTS} times running. "
            f"Last error: {last_error}"
        )

    def _reviewed(
        self,
        prompt: prompts.ModelPrompt,
        schema: type[R],
        specification: Specification,
        context: InterviewContext | None,
        scope: PatchScope | None,
        validate: Callable[[R], None] | None = None,
    ) -> R:
        """Ask for a result with patches, and review them as the driver will apply them."""
        scope = scope or PatchScope(
            fixture_names=frozenset(context.document_names if context else [])
        )
        seen: set[PatchReason] = set()

        def review(candidate: R) -> list[PatchProblem]:
            problems = review_patches(specification, candidate.patches, scope).problems
            seen.update(problem.reason for problem in problems)
            return problems

        result, _ = self._ask(prompt, schema, validate=validate, review=review)
        return result.with_problem_reasons(seen)

    def _step(
        self,
        prompt: prompts.ModelPrompt,
        specification: Specification,
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
        required_additions: frozenset[str] = frozenset(),
    ) -> StepResult:
        def validate(candidate: StepResult) -> None:
            missing = required_additions - {
                patch.path for patch in candidate.patches if patch.op is PatchOp.ADD
            }
            if missing:
                raise PatchValueError(
                    "Return at least one ADD patch with a strict Criterion draft for each "
                    "of these current Specification paths: "
                    + ", ".join(sorted(missing))
                    + ". Use IDs from the current Specification, not IDs in source documents."
                )

        return self._reviewed(
            prompt, StepResult, specification, context, scope, validate=validate
        )

    # ── the interview ──────────────────────────────────────────────────────

    def configure_criterion(
        self,
        criterion: Criterion,
        previous: Criterion | None,
        specification: Specification,
        request: str,
        context: InterviewContext | None = None,
    ) -> CriterionConfiguration:
        from metis.wizard.application.matching.matcher import validate_grader_args

        module, name = (criterion.grader_fqn or "").rsplit(".", 1)
        grader = getattr(import_module(module), name)
        fields: dict[str, Any] = {
            name: (field.annotation, deepcopy(field))
            for name, field in grader.args_model.model_fields.items()
            if not (
                name == "criterion"
                and issubclass(grader.args_model, CriterionJudgeArgs)
            )
            and not (
                name in {"model", "max_input_tokens"}
                and issubclass(grader.args_model, JudgeArgs)
            )
        }
        args_type = create_model("AssessmentSettings", __base__=GraderArgs, **fields)
        result_type = create_model(
            "AssessmentConfiguration",
            __config__=ConfigDict(extra="forbid"),
            description=(
                CriterionDescription,
                Field(
                    description="The final assessment rule shown to the user. State what the agent or its output must satisfy. Do not include configuration instructions, grader names, or output format instructions."
                ),
            ),
            grader_args=(
                args_type,
                Field(
                    description="Exact settings for the selected grader to assess the requirement."
                ),
            ),
        )

        def validate(result: BaseModel) -> None:
            data = result.model_dump(mode="json")
            try:
                validate_grader_args(
                    criterion.grader_fqn,
                    data["grader_args"],
                    description=data["description"],
                )
            except ValueError as exc:
                raise PatchValueError(str(exc)) from exc

        prompt = prompts.ModelPrompt(
            name="configure_criterion",
            system=prompts.configure_criterion_system(),
            user=json.dumps(
                {
                    "request": request,
                    "proposed_criterion": criterion.model_dump(mode="json"),
                    "previous_criterion": previous.model_dump(mode="json")
                    if previous
                    else None,
                    "specification": specification.model_dump(mode="json"),
                    # the target connection is never sent to the model or to tracing
                    "context": context.model_dump(mode="json", exclude={"connection"})
                    if context
                    else None,
                    "grader": grader.__doc__,
                    "uses_criterion_description": issubclass(
                        grader.args_model, CriterionJudgeArgs
                    ),
                    "settings_schema": args_type.model_json_schema(),
                }
            ),
        )
        result, _ = self._ask(prompt, result_type, validate=validate)
        configured = CriterionConfiguration.model_validate(
            result.model_dump(mode="json")
        )
        if previous and issubclass(grader.args_model, JudgeArgs):
            for key in ("model", "max_input_tokens"):
                if key in previous.grader_args:
                    configured.grader_args[key] = previous.grader_args[key]
        validate_grader_args(
            criterion.grader_fqn,
            configured.grader_args,
            description=configured.description,
        )
        return configured

    def clarify(
        self,
        specification: Specification,
        history: list[InterviewMessage],
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> ClarifyResult:
        return self._reviewed(
            prompts.clarify(specification, history, context),
            ClarifyResult,
            specification,
            context,
            scope,
        )

    def draft_behaviours(
        self,
        specification: Specification,
        history: list[InterviewMessage],
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> StepResult:
        return self._step(
            prompts.behaviours(specification, history, context),
            specification,
            context,
            scope=scope,
        )

    def draft_criteria(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> StepResult:
        return self._step(
            prompts.criteria(specification, context),
            specification,
            context,
            scope=scope,
            required_additions=missing_criteria_paths(specification),
        )

    def draft_personas(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> StepResult:
        return self._step(
            prompts.personas(specification, context),
            specification,
            context,
            scope=scope,
        )

    def draft_scenarios(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> StepResult:
        return self._step(
            prompts.scenarios(specification, context),
            specification,
            context,
            scope=scope,
        )

    def draft_test_cases(
        self,
        specification: Specification,
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> StepResult:
        return self._step(
            prompts.test_cases(specification, context),
            specification,
            context,
            scope=scope,
        )

    def chat(
        self,
        specification: Specification,
        step: str,
        text: str,
        target: str | None,
        context: InterviewContext | None = None,
        *,
        scope: PatchScope | None = None,
    ) -> StepResult:
        return self._step(
            prompts.chat(specification, step, text, target, context),
            specification,
            context,
            scope=scope,
        )

    # ── grader matching ────────────────────────────────────────────────────

    def select_graders(
        self,
        prompt: prompts.ModelPrompt,
        offered: set[str],
        criterion_ids: set[str],
    ) -> GraderChoices:
        from metis.wizard.application.matching.matcher import check_grader_choices

        def validate(choices: GraderChoices) -> None:
            try:
                check_grader_choices(choices, offered, criterion_ids)
            except ValueError as exc:
                raise PatchValueError(str(exc)) from exc

        result, _ = self._ask(prompt, GraderChoices, validate=validate)
        return result
