"""Loading a target binding: ${NAME} in spec_url, local specs, and secrets (#507)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog

from metis.engine.simulation.binding import (
    TargetBindingError,
    load_target_binding,
)

if TYPE_CHECKING:
    from pathlib import Path

_SENTINELS = ("SENTINEL-KEY", "SENTINEL-MODEL", "SENTINEL-URL")


def _binding(spec_url: str = "${APP_URL}/openapi.json", extra: str = "") -> str:
    return f"""\
schema_version: 1
identity: {{name: App}}
transport: http
spec_url: "{spec_url}"
auth: {{secret_env: APP_KEY}}
secret_headers:
  - {{match: "POST /chat", header: X-Model, env: APP_MODEL}}
{extra}"""


def _write(inputs: Path, text: str, name: str = "targets/app.yaml") -> Path:
    path = inputs / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    folder = tmp_path / "inputs"
    folder.mkdir()
    return folder


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_URL", "https://app.example")
    monkeypatch.setenv("APP_KEY", "SENTINEL-KEY")
    monkeypatch.setenv("APP_MODEL", "SENTINEL-MODEL")


def test_a_valid_binding_loads(inputs: Path) -> None:
    _write(inputs, _binding())

    loaded = load_target_binding(inputs, "targets/app.yaml")

    assert loaded.spec_url == "https://app.example/openapi.json"
    assert loaded.binding.spec_url == "${APP_URL}/openapi.json"
    key = loaded.secret("APP_KEY")
    model = loaded.secret("APP_MODEL")
    assert key is not None and key.get_secret_value() == "SENTINEL-KEY"
    assert model is not None and model.get_secret_value() == "SENTINEL-MODEL"
    assert loaded.path == (inputs / "targets/app.yaml").resolve()


def test_only_spec_url_is_expanded(inputs: Path) -> None:
    _write(inputs, _binding(extra='advice: {notes: "${APP_URL}"}\n'))

    loaded = load_target_binding(inputs, "targets/app.yaml")

    assert loaded.binding.advice.notes == "${APP_URL}"


def test_an_unset_variable_is_named(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_URL")
    _write(inputs, _binding())

    with pytest.raises(
        TargetBindingError,
        match="spec_url needs the environment variable APP_URL, which is not set",
    ):
        load_target_binding(inputs, "targets/app.yaml")


def test_an_empty_variable_counts_as_unset(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_URL", "")
    _write(inputs, _binding())

    with pytest.raises(
        TargetBindingError,
        match="spec_url needs the environment variable APP_URL, which is not set",
    ):
        load_target_binding(inputs, "targets/app.yaml")


def test_a_malformed_reference_is_refused(inputs: Path) -> None:
    _write(inputs, _binding(spec_url="${app_url}/x"))

    with pytest.raises(TargetBindingError, match=r'"\$\{" that is not'):
        load_target_binding(inputs, "targets/app.yaml")


def test_a_value_containing_dollar_brace_expands(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_URL", "https://a.example/${x}")
    _write(inputs, _binding())

    loaded = load_target_binding(inputs, "targets/app.yaml")

    assert loaded.spec_url == "https://a.example/${x}/openapi.json"


def test_a_binding_outside_the_input_folder_is_refused(
    inputs: Path, tmp_path: Path
) -> None:
    _write(tmp_path, _binding(), name="elsewhere/app.yaml")

    with pytest.raises(TargetBindingError, match="must be inside the input folder"):
        load_target_binding(inputs, "../elsewhere/app.yaml")


def test_dotdot_that_stays_inside_is_allowed(inputs: Path) -> None:
    _write(inputs, _binding())

    loaded = load_target_binding(inputs, "targets/../targets/app.yaml")

    assert loaded.binding.identity.name == "App"


def test_a_missing_file_is_named(inputs: Path) -> None:
    with pytest.raises(
        TargetBindingError, match=r"^targets/none\.yaml: target binding file not found$"
    ):
        load_target_binding(inputs, "targets/none.yaml")


def test_a_folder_cannot_be_read(inputs: Path) -> None:
    (inputs / "targets").mkdir()

    with pytest.raises(TargetBindingError, match="cannot be read"):
        load_target_binding(inputs, "targets")


def test_bad_yaml_gives_its_line(inputs: Path) -> None:
    _write(inputs, "a: [\n")

    with pytest.raises(TargetBindingError, match=r"not valid YAML \(line \d+\)"):
        load_target_binding(inputs, "targets/app.yaml")


def test_an_empty_file_is_not_a_mapping(inputs: Path) -> None:
    _write(inputs, "")

    with pytest.raises(TargetBindingError, match="must be a mapping"):
        load_target_binding(inputs, "targets/app.yaml")


def test_a_list_is_not_a_mapping(inputs: Path) -> None:
    _write(inputs, "- a\n- b\n")

    with pytest.raises(TargetBindingError, match="must be a mapping"):
        load_target_binding(inputs, "targets/app.yaml")


def test_an_invalid_shape_reports_validation(inputs: Path) -> None:
    _write(inputs, _binding().replace("transport: http", "transport: grpc"))

    with pytest.raises(TargetBindingError, match="TargetBinding"):
        load_target_binding(inputs, "targets/app.yaml")


def test_a_relative_spec_url_is_a_local_file(inputs: Path) -> None:
    _write(inputs, "{}", name="targets/openapi.json")
    _write(inputs, _binding(spec_url="openapi.json"))

    loaded = load_target_binding(inputs, "targets/app.yaml")

    assert loaded.spec_url == (inputs / "targets/openapi.json").resolve().as_uri()


def test_a_missing_local_spec_is_refused(inputs: Path) -> None:
    _write(inputs, _binding(spec_url="openapi.json"))

    with pytest.raises(TargetBindingError, match="names a file that does not exist"):
        load_target_binding(inputs, "targets/app.yaml")


def test_a_local_spec_outside_the_input_folder_is_refused(
    inputs: Path, tmp_path: Path
) -> None:
    _write(tmp_path, "{}", name="x.json")
    _write(inputs, _binding(spec_url="../../x.json"))

    with pytest.raises(
        TargetBindingError, match="must name a file inside the input folder"
    ):
        load_target_binding(inputs, "targets/app.yaml")


def test_an_absolute_local_spec_url_is_refused(inputs: Path) -> None:
    _write(inputs, _binding(spec_url="/etc/hosts"))

    with pytest.raises(TargetBindingError, match="inside the input folder"):
        load_target_binding(inputs, "targets/app.yaml")


def test_a_refused_scheme_does_not_echo_the_url(inputs: Path) -> None:
    _write(inputs, _binding(spec_url="ftp://${APP_KEY}@host/spec"))

    with pytest.raises(TargetBindingError, match='not "ftp:"') as caught:
        load_target_binding(inputs, "targets/app.yaml")

    assert "sentinel-key" not in str(caught.value).lower()


def test_an_unset_auth_secret_is_an_error(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_KEY")
    _write(inputs, _binding())

    with pytest.raises(
        TargetBindingError, match="auth.secret_env names APP_KEY, which is not set"
    ):
        load_target_binding(inputs, "targets/app.yaml")


def test_an_unset_secret_header_is_left_out_with_a_warning(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_MODEL")
    _write(inputs, _binding())

    with structlog.testing.capture_logs() as logs:
        loaded = load_target_binding(inputs, "targets/app.yaml")

    assert loaded.secret("APP_MODEL") is None
    warnings = [repr(entry) for entry in logs if entry["log_level"] == "warning"]
    assert len(warnings) == 1
    assert "X-Model" in warnings[0]
    assert "APP_MODEL" in warnings[0]


def test_no_secret_appears_in_repr_errors_or_logs(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_URL", "https://SENTINEL-URL.example")
    _write(inputs, _binding())

    with structlog.testing.capture_logs() as logs:
        loaded = load_target_binding(inputs, "targets/app.yaml")

    shown = [repr(loaded), repr(logs)]
    _write(inputs, _binding().replace("transport: http", "transport: grpc"))
    with pytest.raises(TargetBindingError) as invalid:
        load_target_binding(inputs, "targets/app.yaml")
    _write(inputs, _binding())
    monkeypatch.delenv("APP_KEY")
    with pytest.raises(TargetBindingError) as unset:
        load_target_binding(inputs, "targets/app.yaml")
    shown += [str(invalid.value), str(unset.value)]

    for text in shown:
        for sentinel in _SENTINELS:
            assert sentinel.lower() not in text.lower()


@pytest.mark.parametrize(
    ("spec_url", "value"),
    [
        ("http://[${H}]/spec", "SENTINEL-URL"),
        ("http://${H}/spec", "SENTINEL-URL＃x"),
        ("${H}", "SENTINEL-URL" * 30),
    ],
)
def test_an_unusable_expanded_spec_url_does_not_echo_the_value(
    inputs: Path, monkeypatch: pytest.MonkeyPatch, spec_url: str, value: str
) -> None:
    monkeypatch.setenv("H", value)
    _write(inputs, _binding(spec_url=spec_url))

    with pytest.raises(TargetBindingError, match="once expanded") as caught:
        load_target_binding(inputs, "targets/app.yaml")

    assert "sentinel-url" not in str(caught.value).lower()


def test_a_scheme_from_the_environment_is_not_echoed(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("U", "SENTINEL-URL:x@host/spec")
    _write(inputs, _binding(spec_url="${U}"))

    with pytest.raises(TargetBindingError, match="unsupported scheme") as caught:
        load_target_binding(inputs, "targets/app.yaml")

    assert "sentinel-url" not in str(caught.value).lower()


def test_a_binding_that_is_not_utf8_is_a_clear_error(inputs: Path) -> None:
    _write(inputs, "")
    (inputs / "targets/app.yaml").write_bytes(b"identity: \xff\xfe\n")

    with pytest.raises(TargetBindingError, match="not valid UTF-8"):
        load_target_binding(inputs, "targets/app.yaml")


def _browser_binding(start_url: str = "${APP_URL}/login", extra: str = "") -> str:
    return f"""\
schema_version: 1
identity: {{name: App}}
transport: browser
start_url: "{start_url}"
login:
  note: "Type {{{{secret:APP_USER}}}} and {{{{secret:APP_PASSWORD}}}}."
  secrets: [APP_USER, APP_PASSWORD]
{extra}"""


def test_a_browser_binding_loads_with_its_login_secrets(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_USER", "SENTINEL-USER")
    monkeypatch.setenv("APP_PASSWORD", "SENTINEL-PASSWORD")
    _write(inputs, _browser_binding())

    loaded = load_target_binding(inputs, "targets/app.yaml", "browser")

    assert loaded.start_url == "https://app.example/login"
    assert loaded.binding.start_url == "${APP_URL}/login"
    assert loaded.spec_url is None
    password = loaded.secret("APP_PASSWORD")
    assert password is not None and password.get_secret_value() == "SENTINEL-PASSWORD"
    assert "SENTINEL" not in repr(loaded)


def test_a_browser_binding_without_a_login_needs_no_secrets(inputs: Path) -> None:
    _write(
        inputs,
        "schema_version: 1\nidentity: {name: App}\ntransport: browser\n"
        "start_url: https://app.example/\n",
    )

    loaded = load_target_binding(inputs, "targets/app.yaml", "browser")

    assert loaded.start_url == "https://app.example/"
    assert loaded.secrets == {}


def test_an_unset_login_secret_is_named(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_USER", "SENTINEL-USER")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    _write(inputs, _browser_binding())

    with pytest.raises(
        TargetBindingError, match="login.secrets names APP_PASSWORD, which is not set"
    ):
        load_target_binding(inputs, "targets/app.yaml", "browser")


def test_an_unset_start_url_variable_is_named(
    inputs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_URL")
    _write(inputs, _browser_binding())

    with pytest.raises(
        TargetBindingError,
        match="start_url needs the environment variable APP_URL, which is not set",
    ):
        load_target_binding(inputs, "targets/app.yaml", "browser")


@pytest.mark.parametrize(
    "start_url", ["file:///etc/passwd", "/etc/passwd", "about:blank"]
)
def test_a_start_url_must_be_http_or_https(inputs: Path, start_url: str) -> None:
    _write(inputs, _browser_binding(start_url=start_url))

    with pytest.raises(TargetBindingError, match="start_url must be an http"):
        load_target_binding(inputs, "targets/app.yaml", "browser")


def test_a_binding_of_the_other_transport_is_refused(inputs: Path) -> None:
    _write(inputs, _browser_binding())
    _write(inputs, _binding(), name="targets/http.yaml")

    with pytest.raises(TargetBindingError, match="needs a http binding"):
        load_target_binding(inputs, "targets/app.yaml")
    with pytest.raises(TargetBindingError, match="needs a browser binding"):
        load_target_binding(inputs, "targets/http.yaml", "browser")
