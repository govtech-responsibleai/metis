"""The example target bindings, and the README that shows them."""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.core.target_binding import TargetBinding
from metis.engine.simulation.binding import load_target_binding
from metis.engine.simulation.runners.rules import ToolRefused, check_call

ENGINE = Path(__file__).resolve().parents[3] / "packages" / "engine"
EXAMPLE = ENGINE / "examples"
TOY = EXAMPLE / "http-agentic_eval_toyapp-1"
BINDING = TOY / "toyapp-api.yaml"
README = ENGINE / "src/metis/engine/simulation/README.md"
SCHEMA = EXAMPLE.parents[1] / "core" / "schemas" / "target-binding.schema.json"


@pytest.fixture
def binding(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TOYAPP_API_URL", "http://toyapp.example:8000")
    return load_target_binding(TOY, "toyapp-api.yaml")


def test_the_example_loads_and_expands_its_spec_url(binding) -> None:
    assert binding.binding.identity.name == "Agentic Eval Toy App"
    assert binding.spec_url == "http://toyapp.example:8000/openapi.json"
    assert binding.binding.tls_verify is True
    assert binding.binding.auth is None


def test_the_example_points_editors_at_the_published_schema() -> None:
    first = BINDING.read_text(encoding="utf-8").splitlines()[0]

    assert first.startswith("# yaml-language-server: $schema=")
    relative = first.partition("$schema=")[2]
    assert (BINDING.parent / relative).resolve() == SCHEMA.resolve()


def test_the_example_names_the_call_that_sends_the_message(binding) -> None:
    assert binding.binding.submissions == ["POST /api/v1/sessions/*/messages"]


def test_a_forbidden_call_pattern_refuses_a_delete(binding) -> None:
    patterns = ["DELETE /api/v1/**"]
    with pytest.raises(ToolRefused, match="forbidden"):
        check_call("DELETE", "/api/v1/sessions/s-1", patterns)
    check_call("POST", "/api/v1/sessions/s-1/messages", patterns)


def test_the_example_matches_the_model_it_is_written_for() -> None:
    import yaml

    TargetBinding.model_validate(yaml.safe_load(BINDING.read_text(encoding="utf-8")))


def test_the_readme_shows_the_example_exactly() -> None:
    assert BINDING.read_text(encoding="utf-8") in README.read_text(encoding="utf-8")


def test_the_readme_says_it_has_only_been_tried_on_the_toy_app() -> None:
    assert "bundled toy app only" in README.read_text(encoding="utf-8")


WEB_EXAMPLE = EXAMPLE / "browser-chat-1"
WEB_BINDING = WEB_EXAMPLE / "web-chat.yaml"


@pytest.fixture
def web_binding(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHAT_URL", "https://chat.example/")
    monkeypatch.setenv("CHAT_USER", "alice")
    monkeypatch.setenv("CHAT_PASSWORD", "SENTINEL-PASSWORD")
    return load_target_binding(WEB_EXAMPLE, "web-chat.yaml", "browser")


def test_the_browser_example_loads_and_reads_its_login_secrets(web_binding) -> None:
    assert web_binding.start_url == "https://chat.example/"
    assert web_binding.spec_url is None
    assert web_binding.secret("CHAT_PASSWORD") is not None
    assert "{{secret:CHAT_USER}}" in (web_binding.binding.login.note or "")


def test_the_browser_example_points_editors_at_the_published_schema() -> None:
    first = WEB_BINDING.read_text(encoding="utf-8").splitlines()[0]

    relative = first.partition("$schema=")[2]
    assert (WEB_BINDING.parent / relative).resolve() == SCHEMA.resolve()


def test_the_readme_shows_the_browser_example_exactly() -> None:
    assert WEB_BINDING.read_text(encoding="utf-8") in README.read_text(encoding="utf-8")


def test_the_readme_says_the_browser_runner_has_never_met_a_live_page() -> None:
    text = README.read_text(encoding="utf-8")

    assert "Never run against a live page" in text
    assert "`end_chat` does nothing" in text
