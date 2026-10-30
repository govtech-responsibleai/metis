"""The published target binding schema, and a chat app binding validated against it."""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from metis.core.target_binding import TargetBinding


@pytest.fixture
def schema(repo_root: Path) -> dict:
    path = repo_root / "packages/core/schemas/target-binding.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def chat_app(repo_root: Path) -> dict:
    path = repo_root / "tests/fixtures/target_binding/chat-app.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_chat_app_binding_validates_against_model(chat_app):
    binding = TargetBinding.model_validate(chat_app)
    assert binding.spec_url == "${CHAT_API_URL}/openapi.json"
    assert binding.tls_verify is False
    assert binding.auth is not None and binding.auth.secret_env == "CHAT_API_KEY"
    assert binding.secret_headers[0].env == "CHAT_GATEWAY_KEY"
    assert binding.submissions == ["POST /api/v1/chat"]
    assert binding.forbidden_calls == ["DELETE /api/v1/**", "POST /api/v1/chat/cancel"]
    assert binding.preflight_reads == ["/api/v1/usage"]
    assert binding.advice.limits is not None
    assert binding.advice.limits.submit_per_minute == 6


def test_chat_app_binding_validates_against_published_schema(schema, chat_app):
    jsonschema.validate(instance=chat_app, schema=schema)


def test_published_schema_marks_advice(schema):
    assert schema["title"] == "TargetBinding v1"
    assert schema["$defs"]["Advice"]["description"].startswith(
        "Advice for the runner agent"
    )


def test_published_schema_rejects_secret_value(schema, chat_app):
    chat_app["auth"]["secret_env"] = "sk-live-AbC123"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=chat_app, schema=schema)


def test_a_browser_binding_validates_against_published_schema(schema, repo_root):
    path = repo_root / "packages/engine/examples/browser-chat-1/web-chat.yaml"
    example = yaml.safe_load(path.read_text(encoding="utf-8"))

    jsonschema.validate(instance=example, schema=schema)
    TargetBinding.model_validate(example)
