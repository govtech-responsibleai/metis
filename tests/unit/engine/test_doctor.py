"""Tests for `metis doctor`. The network is mocked."""

from __future__ import annotations

import httpx
import pytest
from typer.testing import CliRunner

from metis.engine import doctor
from metis.engine.doctor import Status

SECRET = "sk-super-secret-value"
GOOD_ENV = {
    "OPENAI_API_KEY": SECRET,
    "LANGFUSE_PUBLIC_KEY": "pk-lf-public",
    "LANGFUSE_SECRET_KEY": "sk-lf-secret",
    "LANGFUSE_BASE_URL": "https://langfuse.example",
}


def _by_name(results: list[doctor.CheckResult]) -> dict[str, doctor.CheckResult]:
    return {r.name: r for r in results}


def _mock_http(monkeypatch: pytest.MonkeyPatch, status: int | Exception = 200) -> None:
    def fake_get(url: str, **_: object) -> httpx.Response:
        if isinstance(status, Exception):
            raise status
        return httpx.Response(status, request=httpx.Request("GET", url))

    monkeypatch.setattr(doctor.httpx, "get", fake_get)


def test_valid_env_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch)
    results = doctor.run_checks(GOOD_ENV)
    assert all(r.status is Status.PASS for r in results)


def test_missing_openai_key_fails_and_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch)
    env = {k: v for k, v in GOOD_ENV.items() if k != "OPENAI_API_KEY"}
    by_name = _by_name(doctor.run_checks(env))
    assert by_name["OPENAI_API_KEY"].status is Status.FAIL
    assert by_name["Model gateway connection"].status is Status.SKIP


@pytest.mark.parametrize("name", doctor.LANGFUSE_VARS)
def test_missing_langfuse_var_warns_about_evaluate(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _mock_http(monkeypatch)
    env = {k: v for k, v in GOOD_ENV.items() if k != name}
    by_name = _by_name(doctor.run_checks(env))
    assert by_name[name].status is Status.WARN
    assert "metis engine evaluate" in by_name[name].detail
    assert not any(r.status is Status.FAIL for r in by_name.values())


@pytest.mark.parametrize("code", [401, 403])
def test_wrong_key_fails_and_names_service(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    _mock_http(monkeypatch, code)
    by_name = _by_name(doctor.run_checks(GOOD_ENV))
    assert by_name["Model gateway connection"].status is Status.FAIL
    assert by_name["Langfuse connection"].status is Status.FAIL


def test_timeout_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_http(monkeypatch, httpx.ConnectTimeout("slow"))
    by_name = _by_name(doctor.run_checks(GOOD_ENV))
    assert by_name["Model gateway connection"].status is Status.FAIL


def test_partly_set_internal_trio_warns() -> None:
    env = {**GOOD_ENV, "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY": "pk"}
    result = doctor.check_internal_langfuse(env)
    assert result.status is Status.WARN
    assert "METIS_INTERNAL_LANGFUSE_SECRET_KEY" in result.detail


def test_unset_internal_trio_passes() -> None:
    assert doctor.check_internal_langfuse(GOOD_ENV).status is Status.PASS


def test_output_never_prints_secret_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_http(monkeypatch, 401)
    doctor.report(doctor.run_checks(GOOD_ENV))
    out = capsys.readouterr().out
    for value in GOOD_ENV.values():
        assert value not in out


def test_cli_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    import metis_cli

    monkeypatch.setenv("METIS_ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / ".env").write_text("")
    for name in (*doctor.REQUIRED_VARS, *doctor.LANGFUSE_VARS):
        monkeypatch.delenv(name, raising=False)
    runner = CliRunner()
    assert runner.invoke(metis_cli.app, ["doctor"]).exit_code == 1

    _mock_http(monkeypatch)
    for name, value in GOOD_ENV.items():
        monkeypatch.setenv(name, value)
    assert runner.invoke(metis_cli.app, ["doctor"]).exit_code == 0
