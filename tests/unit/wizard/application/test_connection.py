"""The target connection: binding checks, the client-held state, and the export."""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
import yaml
from pydantic import ValidationError

from metis.core.target_binding import TargetBinding
from metis.wizard import (
    InterviewState,
    SpecificationFixture,
    check_connection,
    package_specification,
    set_connection,
)
from metis.wizard.application.connection import (
    RUNNER_FACTORY_REFS,
    binding_yaml,
    connected_specification,
)
from metis.wizard.contracts import (
    ConnectionStatus,
    ConnectionTransport,
    TargetConnection,
)
from tests.fixtures.wizard.connections import (
    CHAT_DOCUMENT,
    OPENAPI_DOCUMENT,
    PLANTED_SECRET,
    browser_binding,
    connection,
    http_binding,
    mock_client_factory,
)
from tests.fixtures.wizard.context import interview_context
from tests.fixtures.wizard.specifications import research_assistant

ENVIRON = {
    "APP_URL": "https://app.example",
    "APP_KEY": PLANTED_SECRET,
    "APP_USER": "alice",
    "APP_PASSWORD": PLANTED_SECRET,
}


def _no_network(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("the check must not reach the network")


@pytest.mark.parametrize("data", [http_binding(), browser_binding()])
def test_a_valid_binding_passes_the_offline_check_without_a_request(data) -> None:
    factory = mock_client_factory(_no_network)

    result = check_connection(data, live=False, client_factory=factory)

    assert result.valid
    assert result.errors == []
    assert result.live is False
    assert result.status is ConnectionStatus.UNCHECKED
    assert factory.requests == []


@pytest.mark.parametrize(
    ("data", "field"),
    [
        (http_binding(auth={"secret_env": PLANTED_SECRET}), "secret_env"),
        (
            http_binding(
                secret_headers=[
                    {"match": "POST /chat", "header": "X-Key", "env": PLANTED_SECRET}
                ]
            ),
            "env",
        ),
        (
            browser_binding(login={"note": "Sign in.", "secrets": [PLANTED_SECRET]}),
            "secrets",
        ),
        (
            browser_binding(
                login={"note": f"Type {{{{secret:{PLANTED_SECRET}}}}}.", "secrets": []}
            ),
            "login",
        ),
        (
            http_binding(spec_url=f"https://user:{PLANTED_SECRET}@app.example/"),
            "spec_url",
        ),
        (
            browser_binding(start_url=f"https://{PLANTED_SECRET}@app.example/"),
            "start_url",
        ),
    ],
)
def test_an_invalid_binding_names_the_field_and_never_repeats_the_value(
    data, field
) -> None:
    result = check_connection(data, live=True, environ=ENVIRON)

    assert not result.valid
    assert result.errors
    assert any(field in [str(part) for part in error.loc] for error in result.errors)
    assert PLANTED_SECRET not in result.model_dump_json()


def test_a_login_placeholder_must_name_a_listed_secret() -> None:
    result = check_connection(
        browser_binding(login={"note": "Type {{secret:APP_PASSWORD}}.", "secrets": []}),
        live=False,
    )

    assert not result.valid
    assert "does not list APP_PASSWORD" in result.errors[0].msg


def test_the_live_http_check_reads_the_openapi_document() -> None:
    factory = mock_client_factory(lambda _: httpx.Response(200, json=OPENAPI_DOCUMENT))

    result = check_connection(
        http_binding(), live=True, environ=ENVIRON, client_factory=factory
    )

    assert result.status is ConnectionStatus.CHECKED
    assert [probe.name for probe in result.probes] == [
        "APP_URL",
        "APP_KEY",
        "spec_url",
        "server",
    ]
    assert all(probe.ok for probe in result.probes)
    assert result.probes[2].message.startswith("OpenAPI document: ")
    assert result.probes[2].message.endswith(" endpoints") or result.probes[
        2
    ].message.endswith(" endpoint")
    assert factory.requests[1].method == "HEAD"
    assert str(factory.requests[0].url) == "https://app.example/openapi.json"
    # the probes name the URL as written, never the expanded URL or a variable's value
    dumped = result.model_dump_json()
    assert "${APP_URL}/openapi.json" in dumped
    assert "https://app.example" not in dumped
    assert PLANTED_SECRET not in dumped


@pytest.mark.parametrize(
    ("response", "problem"),
    [
        (httpx.Response(200, json={"swagger": "2.0", "paths": {}}), "`openapi`"),
        (httpx.Response(200, text="<html>sign in</html>"), "not an OpenAPI"),
        (
            httpx.Response(401, text=f"bad token {PLANTED_SECRET}"),
            "returned HTTP 401",
        ),
    ],
)
def test_the_live_http_check_reports_an_unusable_target_without_its_body(
    response, problem
) -> None:
    factory = mock_client_factory(lambda _: response)

    result = check_connection(
        http_binding(), live=True, environ=ENVIRON, client_factory=factory
    )

    assert result.valid
    assert result.status is ConnectionStatus.UNCHECKED
    spec_probe = result.probes[-1]
    assert not spec_probe.ok
    assert problem in spec_probe.message
    assert PLANTED_SECRET not in result.model_dump_json()


def test_a_missing_variable_is_named_and_stops_the_request() -> None:
    factory = mock_client_factory(_no_network)

    result = check_connection(
        http_binding(), live=True, environ={"APP_KEY": "set"}, client_factory=factory
    )

    probes = {probe.name: probe for probe in result.probes}
    assert probes["APP_URL"].message == "not set"
    assert probes["spec_url"].message == "not fetched: APP_URL is not set"
    assert result.status is ConnectionStatus.UNCHECKED
    assert factory.requests == []


@pytest.mark.parametrize(
    ("data", "probe"),
    [(http_binding(), "spec_url"), (browser_binding(), "start_url")],
)
def test_without_expansion_a_url_that_names_a_variable_is_not_requested(
    data, probe
) -> None:
    factory = mock_client_factory(_no_network)

    result = check_connection(
        data,
        live=True,
        expand_variables=False,
        environ=ENVIRON,
        client_factory=factory,
    )

    probes = {item.name: item for item in result.probes}
    assert factory.requests == []
    assert probes["APP_URL"].message == "set"
    assert not probes[probe].ok
    assert "names APP_URL" in probes[probe].message
    assert result.status is ConnectionStatus.UNCHECKED


def test_without_expansion_a_url_with_no_variable_is_requested() -> None:
    factory = mock_client_factory(lambda _: httpx.Response(200, json=OPENAPI_DOCUMENT))

    result = check_connection(
        http_binding(spec_url="https://app.example/openapi.json"),
        live=True,
        expand_variables=False,
        environ=ENVIRON,
        client_factory=factory,
    )

    assert result.status is ConnectionStatus.CHECKED
    assert str(factory.requests[0].url) == "https://app.example/openapi.json"


@pytest.mark.parametrize(("status", "ok"), [(200, True), (302, True), (404, False)])
def test_the_live_browser_check_loads_the_start_page(status: int, ok: bool) -> None:
    factory = mock_client_factory(lambda _: httpx.Response(status))

    result = check_connection(
        browser_binding(), live=True, environ=ENVIRON, client_factory=factory
    )

    assert result.probes[-1].ok is ok
    assert result.status is (
        ConnectionStatus.CHECKED if ok else ConnectionStatus.UNCHECKED
    )
    assert str(factory.requests[0].url) == "https://app.example/login"


@pytest.mark.parametrize("transport", list(ConnectionTransport))
def test_the_export_names_the_generic_runner_and_a_binding_that_loads(
    transport: ConnectionTransport,
) -> None:
    target = connection(transport)

    specification = connected_specification(research_assistant(), target)
    written = binding_yaml(target)

    assert specification.runner_factory_ref == RUNNER_FACTORY_REFS[transport]
    assert specification.target_binding == "target-binding.yaml"
    assert TargetBinding.model_validate(yaml.safe_load(written)) == target.binding
    assert "# Required: APP_URL" in written
    assert "did not check" in written


def test_a_spec_only_export_keeps_the_default_runner() -> None:
    original = research_assistant()

    assert connected_specification(original, None) is original
    assert original.target_binding is None


def test_the_connection_travels_in_state_and_a_spec_only_state_omits_it() -> None:
    state = InterviewState(
        specification=research_assistant(), context=interview_context()
    )
    assert "connection" not in state.model_dump(mode="json")["context"]

    connected = set_connection(
        state, connection(ConnectionTransport.BROWSER, ConnectionStatus.CHECKED)
    )

    assert state.context.connection is None
    restored = InterviewState.model_validate_json(connected.model_dump_json())
    assert restored == connected
    assert restored.context.connection is not None
    assert restored.context.connection.status is ConnectionStatus.CHECKED
    assert set_connection(connected, None).context.connection is None


def test_a_connection_in_state_never_repeats_a_rejected_value() -> None:
    state = InterviewState(
        specification=research_assistant(), context=interview_context()
    ).model_dump(mode="json")
    state["context"]["connection"] = {
        "transport": "http",
        "binding": http_binding(auth={"secret_env": PLANTED_SECRET}),
    }

    with pytest.raises(ValidationError) as error:
        InterviewState.model_validate(state)

    assert PLANTED_SECRET not in str(error.value)


def test_the_connection_transport_must_match_the_binding() -> None:
    with pytest.raises(ValidationError):
        TargetConnection.model_validate(
            {"transport": "browser", "binding": http_binding()}
        )


def _fixtures() -> list[SpecificationFixture]:
    return [SpecificationFixture("policy.pdf", io.BytesIO(b"policy bytes"))]


def _outputs(archive_bytes: bytes) -> dict[str, bytes]:
    """The archive's `outputs/` members by path below the dated root folder."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        return {
            name.split("/", 1)[1]: archive.read(name)
            for name in archive.namelist()
            if name.split("/", 1)[1].startswith("outputs/")
        }


@pytest.mark.parametrize("transport", list(ConnectionTransport))
def test_a_manual_specification_with_a_connection_exports_like_an_interview(
    transport: ConnectionTransport,
) -> None:
    target = connection(transport)
    specification = research_assistant()
    state = set_connection(
        InterviewState(specification=specification, context=interview_context()),
        target,
    )

    manual = package_specification(specification, _fixtures(), connection=target)
    interview = package_specification(state, _fixtures())

    assert _outputs(manual.content) == _outputs(interview.content)
    exported = yaml.safe_load(_outputs(manual.content)["outputs/specification.yaml"])
    assert exported["runner_factory_ref"] == RUNNER_FACTORY_REFS[transport]
    assert "outputs/target-binding.yaml" in _outputs(manual.content)
    with zipfile.ZipFile(io.BytesIO(manual.content)) as archive:
        roots = {name.split("/", 1)[0] for name in archive.namelist()}
        assert all(root.endswith("-manual") for root in roots)
        assert not any(
            name.endswith("interview_state.json") for name in archive.namelist()
        )


def test_a_manual_specification_without_a_connection_keeps_the_default_runner() -> None:
    outputs = _outputs(package_specification(research_assistant(), _fixtures()).content)

    assert "outputs/target-binding.yaml" not in outputs
    exported = yaml.safe_load(outputs["outputs/specification.yaml"])
    assert "target_binding" not in exported
    assert exported["runner_factory_ref"] == research_assistant().runner_factory_ref


def test_an_interview_state_takes_its_connection_only_from_the_state() -> None:
    state = InterviewState(
        specification=research_assistant(), context=interview_context()
    )

    with pytest.raises(ValueError, match="own connection"):
        package_specification(state, _fixtures(), connection=connection())


def _check(document: object, **overrides: object):
    factory = mock_client_factory(
        lambda request: (
            httpx.Response(200, json=document)
            if request.method == "GET"
            else httpx.Response(200)
        )
    )
    return check_connection(
        http_binding(**overrides), live=True, environ=ENVIRON, client_factory=factory
    )


def test_the_check_suggests_the_write_that_takes_one_free_text_field() -> None:
    result = _check(CHAT_DOCUMENT)

    assert result.suggested_submissions == ["POST /conversations/*/messages"]
    assert result.warnings == []
    # a suggestion is a hint only: the checked binding keeps what the user wrote
    assert result.binding is not None
    assert result.binding.submissions == []


def test_a_submissions_pattern_that_matches_no_call_gives_a_warning_naming_it() -> None:
    result = _check(
        CHAT_DOCUMENT,
        submissions=["POST /conversations/*/messages", "POST /chats"],
    )

    assert [(warning.loc, warning.msg) for warning in result.warnings] == [
        (["submissions", 1], "POST /chats matches no call in the OpenAPI document.")
    ]
    assert result.binding is not None
    assert result.status is ConnectionStatus.CHECKED


@pytest.mark.parametrize(
    "document",
    [
        {**OPENAPI_DOCUMENT, "paths": {"/upload": CHAT_DOCUMENT["paths"]["/upload"]}},
        {
            **OPENAPI_DOCUMENT,
            "paths": {"/settings": CHAT_DOCUMENT["paths"]["/settings"]},
        },
    ],
)
def test_a_document_with_no_chat_like_write_suggests_nothing(document) -> None:
    result = _check(document)

    assert result.suggested_submissions == []
    assert result.errors == []


def test_without_a_document_the_check_suggests_nothing_and_warns_nothing() -> None:
    factory = mock_client_factory(lambda _: httpx.Response(404))

    result = check_connection(
        http_binding(submissions=["POST /chats"]),
        live=True,
        environ=ENVIRON,
        client_factory=factory,
    )

    assert result.suggested_submissions == []
    assert result.warnings == []
    assert result.binding is not None
