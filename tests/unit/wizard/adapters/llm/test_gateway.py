"""The model client: credentials, the retry loop, and the primer."""

import json
from dataclasses import dataclass, field

import httpx
import pytest
from openai import APIConnectionError

from metis.core.model_settings import MODEL_GUIDE, ModelRole, resolve_role
from metis.wizard.adapters.llm.gateway import (
    ATTEMPTS,
    CredentialsMissing,
    GatewayInterviewer,
    ModelOutputError,
    check_credentials,
    tracing_key,
)
from metis.wizard.application import prompts
from metis.wizard.application.interviewer import (
    InterviewerOutputError,
)
from metis.wizard.contracts import (
    ClarifyResult,
    Specification,
    Target,
)
from metis.wizard.contracts.output import GraderChoice, GraderChoices
from tests.fixtures.wizard.context import interview_context


@dataclass
class FakeCompletions:
    """Returns a scripted sequence of raw strings, recording what it was sent."""

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


def interviewer(replies: list[str]) -> tuple[GatewayInterviewer, FakeCompletions]:
    completions = FakeCompletions(replies=replies)
    return GatewayInterviewer(_client=FakeClient(completions=completions)), completions


def simple_prompt(name: prompts.ModelCall = "clarify") -> prompts.ModelPrompt:
    return prompts.ModelPrompt(name=name, system="s", user="u")


_ROLE_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "INTERVIEW_API_KEY",
    "INTERVIEW_BASE_URL",
    "INTERVIEW_MODEL",
)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ROLE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("OPENAI_API_KEY", "key")


# ── credentials ────────────────────────────────────────────────────────────


def test_missing_credentials_name_variables_and_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix is to export something, so the message says what and where to read more."""
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(CredentialsMissing) as exc:
        check_credentials()

    message = str(exc.value)
    assert "INTERVIEW_API_KEY or OPENAI_API_KEY" in message
    assert MODEL_GUIDE in message
    assert "https://gateway.example" not in message


def test_credentials_are_checked_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(CredentialsMissing):
        GatewayInterviewer()


def test_the_interview_role_builds_one_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERVIEW_BASE_URL", "https://interview.example")
    built: list[dict[str, object]] = []

    import langfuse.openai

    monkeypatch.setattr(
        langfuse.openai, "OpenAI", lambda **kwargs: built.append(kwargs) or kwargs
    )
    gateway = GatewayInterviewer(
        interview=resolve_role(ModelRole.INTERVIEW, {"OPENAI_API_KEY": "k"}),
    )

    assert gateway.model == "gpt-6-luna"
    assert [b["base_url"] for b in built] == [None]


def test_a_grader_choice_outside_the_offer_is_retried_with_the_error() -> None:
    bad = GraderChoices(
        choices=[GraderChoice(criterion_id="AC-1-1", grader="not.Offered")]
    ).model_dump_json()
    good = GraderChoices(
        choices=[GraderChoice(criterion_id="AC-1-1", grader="tests.Offered")]
    ).model_dump_json()
    model, completions = interviewer([bad, good])

    result = model.select_graders(
        simple_prompt("match_graders"), {"tests.Offered"}, {"AC-1-1"}
    )

    assert result.choices[0].grader == "tests.Offered"
    assert len(completions.calls) == 2
    assert "not.Offered" in completions.calls[1]["messages"][3]["content"]


def test_gateway_connection_failure_is_a_retryable_interviewer_error() -> None:
    class BrokenCompletions:
        def create(self, **_kwargs):
            raise APIConnectionError(
                request=httpx.Request("POST", "https://gateway.example")
            )

    class BrokenClient:
        chat = type("Chat", (), {"completions": BrokenCompletions()})()

    gateway = GatewayInterviewer(_client=BrokenClient())

    with pytest.raises(InterviewerOutputError, match="could not complete"):
        gateway.clarify(
            specification=Specification(
                target=Target(name="", description="", users="")
            ),
            history=[],
            context=interview_context(),
        )


# ── the retry loop ─────────────────────────────────────────────────────────


def test_a_first_attempt_miss_is_invisible() -> None:
    """A schema miss is common and recoverable; the user should never learn it happened."""
    good = ClarifyResult(message="What does it do?", done=False).model_dump_json()
    model, completions = interviewer(["{not json at all", good])

    result, recovered = model._ask(simple_prompt(), ClarifyResult)

    assert result.message == "What does it do?"
    assert recovered  # a retry was needed, and the caller is told so
    assert len(completions.calls) == 2


def test_a_first_attempt_success_reports_no_recovery() -> None:
    """The flag is what lets a step keep the model's intro when nothing went wrong."""
    good = ClarifyResult(message="What does it do?", done=False).model_dump_json()
    model, _ = interviewer([good])

    _, recovered = model._ask(simple_prompt(), ClarifyResult)

    assert not recovered


def test_the_validation_error_is_fed_back() -> None:
    """Retrying blind would be a worse use of the second attempt."""
    good = ClarifyResult(message="", done=True).model_dump_json()
    model, completions = interviewer(["{}", good])

    model._ask(simple_prompt(), ClarifyResult)

    retry_messages = completions.calls[1]["messages"]
    assert [message["role"] for message in retry_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert retry_messages[2]["content"] == "{}"
    assert retry_messages[3]["content"]


def test_a_recovered_step_drops_its_narrated_intro() -> None:
    """A retried turn tends to narrate the fix ("I've corrected the format"). That intro is
    implementation detail — it must never reach the user, so the gateway blanks it in code
    rather than trusting the model not to write it. The patches, the real output, survive."""
    from metis.wizard.contracts import StepResult
    from tests.fixtures.wizard.specifications import research_assistant

    bad = "{not json at all"
    corrected = StepResult(
        message="I've corrected the criteria format to use proper objects.",
        patches=[],
    ).model_dump_json()
    model, completions = interviewer([bad, corrected])

    result = model._step(simple_prompt("chat"), research_assistant())

    assert (
        result.message == ""
    )  # the narration is gone; driver shows its neutral default
    assert len(completions.calls) == 2


def test_a_clean_step_keeps_the_model_intro() -> None:
    """First-attempt output is trusted — the justification the model writes is worth showing."""
    from metis.wizard.contracts import StepResult
    from tests.fixtures.wizard.specifications import research_assistant

    clean = StepResult(
        message="These personas stress citation discipline and scope refusal.",
        patches=[],
    ).model_dump_json()
    model, _ = interviewer([clean])

    result = model._step(simple_prompt("chat"), research_assistant())

    assert (
        result.message == "These personas stress citation discipline and scope refusal."
    )


def test_three_failures_raise() -> None:
    model, completions = interviewer(["nonsense"])

    with pytest.raises(ModelOutputError):
        model._ask(simple_prompt(), ClarifyResult)

    assert len(completions.calls) == ATTEMPTS


def test_raw_scenario_fields_are_rejected_before_specification_materialization() -> (
    None
):
    """The regression starts at provider JSON, before a typed Scenario can exist."""
    from tests.fixtures.wizard.specifications import research_assistant

    invalid = json.dumps(
        {
            "message": "draft",
            "patches": [
                {
                    "op": "add",
                    "path": "scenarios",
                    "value": {
                        "id": "MODEL-ID",
                        "name": "Invalid scenario",
                        "description": "x",
                        "num_trials": 99,
                        "tasks": [],
                    },
                }
            ],
        }
    )
    valid = json.dumps(
        {
            "message": "draft",
            "patches": [
                {
                    "op": "add",
                    "path": "scenarios",
                    "value": {"name": "A scenario", "description": "x"},
                }
            ],
        }
    )
    model, completions = interviewer([invalid, valid])

    result = model._step(simple_prompt("chat"), research_assistant())

    assert result.patches[0].value.description == "x"
    assert len(completions.calls) == 2
    retry_messages = completions.calls[1]["messages"]
    assert [message["role"] for message in retry_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert retry_messages[2]["content"] == invalid
    assert retry_messages[3]["content"]


def test_raw_nested_fields_are_rejected_and_corrected_atomically() -> None:
    from tests.fixtures.wizard.specifications import research_assistant

    invalid = json.dumps(
        {
            "message": "draft",
            "patches": [
                {
                    "op": "add",
                    "path": "features",
                    "value": {
                        "name": "Safety",
                        "behaviours": [
                            {
                                "name": "Refuse unsafe requests",
                                "description": "refuses unsafe requests",
                                "measured": True,
                                "criteria": [{"grader_fqn": "forbidden"}],
                            }
                        ],
                    },
                }
            ],
        }
    )
    valid = json.dumps(
        {
            "message": "draft",
            "patches": [
                {
                    "op": "add",
                    "path": "features",
                    "value": {
                        "name": "Safety",
                        "description": "Safety behaviours",
                        "behaviours": [
                            {
                                "name": "Refuse unsafe requests",
                                "description": "refuses unsafe requests",
                            }
                        ],
                    },
                }
            ],
        }
    )
    model, completions = interviewer([invalid, valid])

    result = model._step(simple_prompt("chat"), research_assistant())

    assert result.patches[0].value.name == "Safety"
    assert len(completions.calls) == 2


def test_structured_output_is_requested_strictly() -> None:
    model, completions = interviewer(
        [ClarifyResult(message="", done=True).model_dump_json()]
    )

    model._ask(simple_prompt(), ClarifyResult)

    schema = completions.calls[0]["response_format"]
    assert schema["type"] == "json_schema"
    assert schema["json_schema"]["strict"] is True

    def objects(node):
        if isinstance(node, dict):
            if "properties" in node:
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    for node in objects(schema["json_schema"]["schema"]):
        assert node["required"] == list(node["properties"])


def test_nulls_for_defaulted_fields_take_the_default() -> None:
    reply = json.dumps(
        {
            "message": "Added a persona.",
            "done": None,
            "patches": [
                {
                    "op": "add",
                    "path": "personas",
                    "value": {
                        "name": "Ana",
                        "description": "A tester.",
                        "metadata": None,
                    },
                }
            ],
        }
    )
    model, _ = interviewer([reply])

    result, recovered = model._ask(simple_prompt(), ClarifyResult)

    assert recovered is False
    assert result.done is False
    assert result.patches[0].value.metadata == {}


def test_model_schema_has_no_persisted_or_runtime_fields() -> None:
    from metis.wizard.contracts import StepResult

    schema = StepResult.model_json_schema()

    def properties(node):
        if isinstance(node, dict):
            yield from node.get("properties", {}).keys()
            for value in node.values():
                yield from properties(value)
        elif isinstance(node, list):
            for value in node:
                yield from properties(value)

    names = set(properties(schema))
    assert not names & {
        "id",
        "measured",
        "grader_fqn",
        "grader_args",
        "num_trials",
        "origin",
        "options",
    }


def test_model_origin_is_not_part_of_provider_schema() -> None:
    """The provider cannot claim the runtime trust marker."""
    bad = json.dumps(
        {
            "message": "done",
            "patches": [
                {
                    "op": "set",
                    "path": "personas[cooperative-delegator].description",
                    "value": "x",
                    "origin": "wizard",
                }
            ],
        }
    )
    good = json.dumps({"message": "done", "patches": []})
    model, completions = interviewer([bad, good])
    from tests.fixtures.wizard.specifications import research_assistant

    result = model._step(simple_prompt("chat"), research_assistant())

    assert result.patches == []
    assert len(completions.calls) == 2


def test_a_malformed_nested_patch_value_is_retried_atomically() -> None:
    """The patch envelope is valid, but its value is not a Feature.

    The model-facing schema and domain validation belong inside the same retry loop. The
    failed attempt must not apply its earlier target edit to the real specification.
    """
    from metis.wizard.contracts import FeatureDraft, Specification, Target

    specification = Specification(target=Target(name="X", description="", users=""))
    bad = json.dumps(
        {
            "message": "drafted",
            "patches": [
                {
                    "op": "set",
                    "path": "target.description",
                    "value": "changed too early",
                },
                {
                    "op": "add",
                    "path": "features",
                    "value": {
                        "name": "Routing",
                        "description": "Routing requests.",
                        "behaviours": [
                            {
                                "name": "Route requests",
                                "description": "",
                                "measured": True,
                            }
                        ],
                    },
                },
            ],
        }
    )
    empty = json.dumps(
        {
            "message": "drafted",
            "patches": [
                {
                    "op": "add",
                    "path": "features",
                    "value": {
                        "name": "Routing",
                        "description": "Routing requests.",
                        "behaviours": [],
                    },
                }
            ],
        }
    )
    good = json.dumps(
        {
            "message": "drafted",
            "patches": [
                {
                    "op": "set",
                    "path": "target.description",
                    "value": "an orchestrator",
                },
                {
                    "op": "add",
                    "path": "features",
                    "value": {
                        "name": "Routing",
                        "description": "Routing requests.",
                        "behaviours": [
                            {
                                "name": "Route requests",
                                "description": "Routes to the right agent",
                            }
                        ],
                    },
                },
            ],
        }
    )
    model, completions = interviewer([bad, empty, good])

    result = model.draft_behaviours(specification, [], context=interview_context())

    assert len(completions.calls) == 3
    feature = result.patches[-1].value
    assert isinstance(feature, FeatureDraft)
    assert feature.behaviours[0].description
    assert specification.target.description == ""
    assert specification.features == []
    retry_messages = completions.calls[2]["messages"]
    assert [message["role"] for message in retry_messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert retry_messages[2]["content"] == bad
    assert retry_messages[4]["content"] == empty
    assert all(message["content"] for message in retry_messages[3::2])


def test_a_duplicate_persona_description_is_retried() -> None:
    from metis.wizard.contracts import PersonaDraft, StepResult, StepResultPatch
    from tests.fixtures.wizard.specifications import research_assistant

    specification = research_assistant()
    existing = specification.personas[0]
    duplicate = StepResult(
        message="added",
        patches=[
            StepResultPatch(
                op="add",
                path="personas",
                value=PersonaDraft(name="Duplicate", description=existing.description),
            )
        ],  # type: ignore[list-item]
    ).model_dump_json()
    good = StepResult(message="updated", patches=[]).model_dump_json()
    model, completions = interviewer([duplicate, good])

    result = model.chat(specification, "personas", "Use these personas instead", None)

    assert result.patches == []
    assert len(completions.calls) == 2
    retry_messages = completions.calls[1]["messages"]
    assert [message["role"] for message in retry_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert retry_messages[2]["content"] == duplicate
    assert retry_messages[3]["content"]


def test_chat_prompt_includes_the_user_message_and_scope_data() -> None:
    from tests.fixtures.wizard.specifications import research_assistant

    prompt = prompts.chat(
        research_assistant(),
        "personas",
        "CHAT_MESSAGE_SENTINEL",
        "TARGET_SENTINEL",
    ).user

    assert "CHAT_MESSAGE_SENTINEL" in prompt
    assert "TARGET_SENTINEL" in prompt


def test_each_semantic_call_sends_one_complete_named_prompt() -> None:
    from metis.wizard.contracts import StepResult
    from tests.fixtures.wizard.specifications import research_assistant

    specification = research_assistant()
    context = interview_context()
    cases = [
        (
            "clarify",
            lambda model: model.clarify(specification, [], context=context),
            lambda: prompts.clarify(specification, [], context=context),
            ClarifyResult(message="", done=True).model_dump_json(),
        ),
        (
            "behaviours",
            lambda model: model.draft_behaviours(specification, [], context=context),
            lambda: prompts.behaviours(specification, [], context=context),
            StepResult(message="", patches=[]).model_dump_json(),
        ),
        (
            "criteria",
            lambda model: model.draft_criteria(specification, context=context),
            lambda: prompts.criteria(specification, context=context),
            StepResult(message="", patches=[]).model_dump_json(),
        ),
        (
            "personas",
            lambda model: model.draft_personas(specification, context=context),
            lambda: prompts.personas(specification, context=context),
            StepResult(message="", patches=[]).model_dump_json(),
        ),
        (
            "scenarios",
            lambda model: model.draft_scenarios(specification, context=context),
            lambda: prompts.scenarios(specification, context=context),
            StepResult(message="", patches=[]).model_dump_json(),
        ),
        (
            "chat",
            lambda model: model.chat(
                specification, "criteria", "edit", "EB-1", context=context
            ),
            lambda: prompts.chat(
                specification, "criteria", "edit", "EB-1", context=context
            ),
            StepResult(message="", patches=[]).model_dump_json(),
        ),
    ]

    for name, invoke, compose, reply in cases:
        model, completions = interviewer([reply])
        expected = compose()

        invoke(model)

        assert expected.name == name
        assert completions.calls[0]["messages"] == [
            {"role": "system", "content": expected.system},
            {"role": "user", "content": expected.user},
        ]


# ── tracing rides on the client ──────────────────────────────────────────────


def test_an_unconfigured_interview_still_completes_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no internal Langfuse env (the conftest default), tracing is off and the call is
    unaffected — the interview never depends on a trace backend being reachable."""
    good = ClarifyResult(message="What does it do?", done=False).model_dump_json()
    model, completions = interviewer([good])

    result, _ = model._ask(simple_prompt(), ClarifyResult)

    assert result.message == "What does it do?"
    assert len(completions.calls) == 1


TARGET_LANGFUSE = {
    "LANGFUSE_PUBLIC_KEY": "pk-target",
    "LANGFUSE_SECRET_KEY": "sk-target",
    "LANGFUSE_BASE_URL": "https://target.example",
}


def test_tracing_uses_only_the_metis_internal_langfuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client gets the internal keys explicitly, so the SDK never reads `LANGFUSE_*`, and
    every model call names that client."""
    from metis.wizard.adapters.llm import gateway

    built: list[dict[str, object]] = []
    monkeypatch.setattr(gateway, "Langfuse", lambda **kwargs: built.append(kwargs))
    env = {
        **TARGET_LANGFUSE,
        "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY": "pk-internal",
        "METIS_INTERNAL_LANGFUSE_SECRET_KEY": "sk-internal",
        "METIS_INTERNAL_LANGFUSE_BASE_URL": "https://internal.example",
    }
    good = ClarifyResult(message="What does it do?", done=False).model_dump_json()
    completions = FakeCompletions(replies=[good])
    model = GatewayInterviewer(
        _client=FakeClient(completions=completions), _tracing_key=tracing_key(env)
    )

    model._ask(simple_prompt(), ClarifyResult)

    assert built == [
        {
            "public_key": "pk-internal",
            "secret_key": "sk-internal",
            "base_url": "https://internal.example",
        }
    ]
    assert completions.calls[0]["langfuse_public_key"] == "pk-internal"


def test_the_target_langfuse_is_never_a_tracing_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without all three internal variables, tracing is off. The target's keys would put
    Interview content in the target's project."""
    from metis.wizard.adapters.llm import gateway

    built: list[dict[str, object]] = []
    monkeypatch.setattr(gateway, "Langfuse", lambda **kwargs: built.append(kwargs))

    key = tracing_key(TARGET_LANGFUSE)

    assert [client["tracing_enabled"] for client in built] == [False]
    assert key not in TARGET_LANGFUSE.values()


def test_the_gateway_builds_its_client_from_the_langfuse_drop_in() -> None:
    """The one wiring that carries tracing: the gateway imports its OpenAI client from
    `langfuse.openai`, whose import patches the client so every call is traced with no tracing
    code on the call path. Langfuse patches openai in place, so `langfuse.openai.OpenAI is
    openai.OpenAI` — the drop-in is not a distinct class to isinstance-check. The honest signal
    is the gateway's own import; assert on its source so the wiring can't silently regress to
    the untraced `from openai import OpenAI`."""
    import inspect

    from metis.wizard.adapters.llm import gateway

    source = inspect.getsource(gateway)

    assert "from langfuse.openai import OpenAI" in source
    assert "from openai import OpenAI" not in source


# ── the primer ─────────────────────────────────────────────────────────────


def test_the_primer_is_in_the_system_prompt() -> None:
    from tests.fixtures.wizard.specifications import research_assistant

    system = prompts.criteria(research_assistant()).system

    primer = prompts.primer()
    assert primer in system
    assert primer in system[system.index("<primer>") : system.index("</primer>")]


def test_changing_the_primer_file_changes_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is a file so it can be tuned without touching code or redeploying."""
    from tests.fixtures.wizard.specifications import research_assistant

    monkeypatch.setattr(prompts, "primer", lambda: "REPLACED PRIMER TEXT")

    assert "REPLACED PRIMER TEXT" in prompts.criteria(research_assistant()).system


@pytest.mark.parametrize("path", ["personas", "scenarios"])
@pytest.mark.parametrize(
    "metadata", [None, {}, {"custom key": "Supplied context", "another": ""}]
)
def test_generated_metadata_reaches_saved_specification(path, metadata):
    from metis.wizard.domain.applier import apply, sanitise
    from tests.fixtures.wizard.specifications import research_assistant

    specification = research_assistant()
    context = interview_context()
    context.opening_description = "Review a policy."
    draft = {
        "name": "Evidence example",
        "description": "Uses the supplied policy context.",
    }
    if metadata is not None:
        draft["metadata"] = metadata
        context.opening_description += " Supplied metadata: " + json.dumps(metadata)
    model, completions = interviewer(
        [
            json.dumps(
                {
                    "message": "Draft",
                    "patches": [{"op": "add", "path": path, "value": draft}],
                }
            )
        ]
    )

    result = getattr(model, f"draft_{path}")(specification, context=context)
    applied = apply(specification, sanitise(result.patches))

    assert not applied.rejected
    restored = type(specification).model_validate_json(specification.model_dump_json())
    saved = getattr(restored, path)[-1]
    assert saved.metadata == (metadata or {})
    assert saved.description == draft["description"]
    assert len(completions.calls) == 1
    messages = completions.calls[0]["messages"]
    assert "Review a policy." in messages[0]["content"]
    assert "`metadata`" in messages[1]["content"]
    assert "No key is required." in messages[1]["content"]


@pytest.mark.parametrize(
    "context_tokens, replies, calls",
    [
        (5000, ["{}"], 0),
        (30000, ["x" * 30000], 1),
    ],
)
def test_context_budget_covers_schema_output_and_retries(
    context_tokens, replies, calls
) -> None:
    from metis.wizard.application.interviewer import InterviewContextBudgetError

    gateway, completions = interviewer(replies)
    gateway.context_tokens = context_tokens
    gateway.output_tokens = 1000
    with pytest.raises(InterviewContextBudgetError, match="No input was truncated"):
        gateway._ask(simple_prompt(), ClarifyResult)
    assert len(completions.calls) == calls


@pytest.mark.parametrize(
    "first_patches",
    [
        [],
        [
            {
                "op": "add",
                "path": "features[source-feature].behaviours[source-behaviour].criteria",
                "value": {
                    "name": "Accuracy",
                    "description": "Given Evidence, when Answering, then Use evidence.",
                },
            }
        ],
    ],
)
def test_criteria_generation_retries_until_measured_gaps_are_filled(
    first_patches,
) -> None:
    from tests.fixtures.wizard.specifications import research_assistant

    specification = research_assistant()
    behaviour = specification.measured_behaviours()[0]
    behaviour.criteria = []
    feature = specification.feature_of(behaviour.id)
    path = f"features[{feature.id}].behaviours[{behaviour.id}].criteria"
    good = {
        "message": "",
        "patches": [
            {
                "op": "add",
                "path": path,
                "value": {
                    "name": "Accuracy",
                    "description": "Given Evidence, when Answering, then Use evidence.",
                },
            }
        ],
    }
    gateway, completions = interviewer(
        [
            json.dumps({"message": "", "patches": first_patches}),
            json.dumps(good),
        ]
    )
    result = gateway.draft_criteria(specification)
    assert len(completions.calls) == 2
    assert result.patches[0].path == path
    assert path in completions.calls[1]["messages"][-1]["content"]
    assert behaviour.criteria == []
