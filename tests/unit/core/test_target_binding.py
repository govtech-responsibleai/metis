"""TargetBinding: the hand-written file that binds an app to the generic HTTP runner."""

import pytest
from pydantic import ValidationError

from metis.core.target_binding import TargetBinding


def _minimal(**overrides):
    data = {
        "schema_version": 1,
        "identity": {"name": "App"},
        "transport": "http",
        "spec_url": "https://app.example/openapi.json",
    }
    data.update(overrides)
    return data


def test_minimal_binding_takes_defaults():
    binding = TargetBinding.model_validate(_minimal())
    assert binding.tls_verify is True
    assert binding.auth is None
    assert binding.secret_headers == []
    assert binding.submissions == []
    assert binding.forbidden_calls == []
    assert binding.preflight_reads == []
    assert binding.advice.notes == ""
    assert binding.advice.limits is None


def test_env_references_are_kept_as_written(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)
    binding = TargetBinding.model_validate(_minimal(spec_url="${APP_URL}/openapi.json"))
    assert binding.spec_url == "${APP_URL}/openapi.json"


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth": {"secret_env": "sk-live-AbC123"}},
        {
            "secret_headers": [
                {"match": "POST /chat", "header": "X-Key", "env": "sk-live-AbC123"}
            ]
        },
    ],
)
def test_secret_value_in_place_of_env_name_is_rejected_without_echo(overrides):
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(_minimal(**overrides))
    assert "sk-live-AbC123" not in str(error.value)


@pytest.mark.parametrize(
    "pattern",
    [
        "post /chat",
        "POST chat",
        "POST  /chat",
        "FETCH /chat",
        "/chat",
        "DELETE /api/v1/sessions/{sessionId}",
        "POST /chat?x=1",
        "GET /chat#top",
    ],
)
def test_malformed_call_pattern_rejected(pattern):
    with pytest.raises(ValidationError):
        TargetBinding.model_validate(_minimal(forbidden_calls=[pattern]))


@pytest.mark.parametrize(
    "pattern", ["DELETE /api/v1/**", "* /admin/*", "POST /api/v1/chat"]
)
def test_call_patterns_accepted(pattern):
    binding = TargetBinding.model_validate(
        _minimal(submissions=[pattern], forbidden_calls=[pattern])
    )
    assert binding.forbidden_calls == [pattern]
    assert binding.submissions == [pattern]


def _browser(**overrides):
    data = {
        "schema_version": 1,
        "identity": {"name": "App"},
        "transport": "browser",
        "start_url": "${APP_URL}/login",
    }
    data.update(overrides)
    return data


def test_minimal_browser_binding_takes_defaults():
    binding = TargetBinding.model_validate(_browser())
    assert binding.start_url == "${APP_URL}/login"
    assert binding.spec_url is None
    assert binding.login is None
    assert binding.advice.notes == ""


def test_browser_login_names_secrets_and_notes_how_to_sign_in():
    binding = TargetBinding.model_validate(
        _browser(
            login={
                "note": "Type {{secret:APP_USER}} in the email box.",
                "secrets": ["APP_USER", "APP_PASSWORD"],
            }
        )
    )
    assert binding.login is not None
    assert binding.login.secrets == ["APP_USER", "APP_PASSWORD"]


def test_browser_login_secret_value_in_place_of_env_name_is_rejected_without_echo():
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(
            _browser(login={"note": "Sign in.", "secrets": ["hunter2-password"]})
        )
    assert "hunter2-password" not in str(error.value)


def test_browser_binding_needs_a_start_url():
    data = _browser()
    del data["start_url"]
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(data)
    assert "start_url" in str(error.value)


def test_http_binding_needs_a_spec_url():
    data = _minimal()
    del data["spec_url"]
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(data)
    assert "spec_url" in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"spec_url": "https://app.example/openapi.json"},
        {"tls_verify": False},
        {"auth": {"secret_env": "APP_KEY"}},
        {"secret_headers": []},
        {"submissions": ["POST /chat"]},
        {"forbidden_calls": ["DELETE /**"]},
        {"preflight_reads": ["/usage"]},
    ],
)
def test_browser_binding_rejects_http_only_fields(overrides):
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(_browser(**overrides))
    assert "browser" in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_url": "https://app.example"},
        {"login": {"note": "Sign in.", "secrets": []}},
    ],
)
def test_http_binding_rejects_browser_only_fields(overrides):
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(_minimal(**overrides))
    assert "http" in str(error.value)


def test_unknown_transport_rejected():
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(_minimal(transport="grpc"))
    assert "transport" in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [{"forbiden_calls": []}, {"notes": "x"}, {"advice": {"limits": {"burst": 3}}}],
)
def test_unknown_keys_rejected(overrides):
    with pytest.raises(ValidationError):
        TargetBinding.model_validate(_minimal(**overrides))


@pytest.mark.parametrize("version", [None, 2])
def test_schema_version_is_required_and_pinned(version):
    data = _minimal()
    if version is None:
        del data["schema_version"]
    else:
        data["schema_version"] = version
    with pytest.raises(ValidationError):
        TargetBinding.model_validate(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"advice": {"limits": {"submit_per_minute": 0}}},
        {"preflight_reads": ["api/v1/usage"]},
        {"preflight_reads": ["/api/v1/usage?days=7"]},
        {"preflight_reads": ["/api/v1/users/{userId}"]},
        {"identity": {"name": ""}},
        {"secret_headers": [{"match": "POST /chat", "header": "X Key", "env": "KEY"}]},
    ],
)
def test_invalid_values_rejected(overrides):
    with pytest.raises(ValidationError):
        TargetBinding.model_validate(_minimal(**overrides))


@pytest.mark.parametrize(
    ("note", "secrets", "named"),
    [
        ("Type {{secret:APP_PASSWORD}}.", ["APP_USER"], "APP_PASSWORD"),
        ("Type {{secret:APP_USER}}.", [], "APP_USER"),
    ],
)
def test_login_note_placeholder_must_be_listed_in_secrets(note, secrets, named):
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(_browser(login={"note": note, "secrets": secrets}))
    assert f"does not list {named}" in str(error.value)


def test_login_note_placeholder_that_is_not_a_name_is_rejected_without_echo():
    with pytest.raises(ValidationError) as error:
        TargetBinding.model_validate(
            _browser(login={"note": "Type {{secret:hunter2-password}}.", "secrets": []})
        )
    assert "hunter2-password" not in str(error.value)
    assert "not an environment variable name" in str(error.value)
