"""The target's Langfuse project lookup and the session URLs built from it."""

from __future__ import annotations

import base64

import httpx
import pytest

from metis.core.langfuse_links import (
    TargetProject,
    session_url,
    target_langfuse_project,
)

_KEYS = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}


def _transport(
    body: object = None, status: int = 200, *, seen: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(body, (bytes, str)):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def _never_called() -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    return httpx.MockTransport(handle)


def test_project_found() -> None:
    seen: list[httpx.Request] = []
    env = {**_KEYS, "LANGFUSE_BASE_URL": "https://lf.example/langfuse/"}
    project = target_langfuse_project(
        env, transport=_transport({"data": [{"id": "p1"}]}, seen=seen)
    )
    assert project == TargetProject("https://lf.example/langfuse", "p1")
    (request,) = seen
    assert str(request.url) == "https://lf.example/langfuse/api/public/projects"
    assert (
        request.headers["authorization"]
        == "Basic " + base64.b64encode(b"pk:sk").decode()
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"LANGFUSE_HOST": "https://host.example"}, "https://host.example"),
        (
            {
                "LANGFUSE_BASE_URL": "https://base.example",
                "LANGFUSE_HOST": "https://host.example",
            },
            "https://base.example",
        ),
        ({}, "https://cloud.langfuse.com"),
    ],
)
def test_base_url_order(extra: dict[str, str], expected: str) -> None:
    seen: list[httpx.Request] = []
    project = target_langfuse_project(
        {**_KEYS, **extra}, transport=_transport({"data": [{"id": "p1"}]}, seen=seen)
    )
    assert project is not None
    assert project.base_url == expected
    assert str(seen[0].url) == f"{expected}/api/public/projects"


@pytest.mark.parametrize("missing", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
def test_missing_key_makes_no_call(missing: str) -> None:
    env = {k: v for k, v in _KEYS.items() if k != missing}
    assert target_langfuse_project(env, transport=_never_called()) is None


def test_ignores_internal_vars() -> None:
    env = {
        "METIS_INTERNAL_LANGFUSE_PUBLIC_KEY": "pk",
        "METIS_INTERNAL_LANGFUSE_SECRET_KEY": "sk",
        "METIS_INTERNAL_LANGFUSE_BASE_URL": "https://internal.example",
    }
    assert target_langfuse_project(env, transport=_never_called()) is None


def test_http_error() -> None:
    assert target_langfuse_project(_KEYS, transport=_transport({}, 401)) is None


def test_transport_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert target_langfuse_project(_KEYS, transport=httpx.MockTransport(handle)) is None


@pytest.mark.parametrize(
    "body",
    [{"data": []}, {"data": "x"}, {}, [], {"data": [{}]}, {"data": [{"id": ""}]}],
)
def test_unusable_list(body: object) -> None:
    assert target_langfuse_project(_KEYS, transport=_transport(body)) is None


def test_body_not_json() -> None:
    assert target_langfuse_project(_KEYS, transport=_transport("<html>")) is None


def test_bad_timeout_value() -> None:
    env = {**_KEYS, "LANGFUSE_TIMEOUT": "abc"}
    project = target_langfuse_project(
        env, transport=_transport({"data": [{"id": "p1"}]})
    )
    assert project is not None


def test_session_url_keeps_prefix_and_encodes_the_session() -> None:
    assert (
        session_url("https://lf.example/langfuse/", "p1", "a/b #?c")
        == "https://lf.example/langfuse/project/p1/sessions/a%2Fb%20%23%3Fc"
    )


def test_session_url_without_prefix() -> None:
    assert session_url("https://x", "p1", "s") == "https://x/project/p1/sessions/s"


def test_project_builds_session_urls() -> None:
    project = TargetProject("https://x/langfuse", "p1")
    assert project.session_url("s-1") == "https://x/langfuse/project/p1/sessions/s-1"


@pytest.mark.parametrize(
    "base_url",
    ["http://host:abc", "https://cloud.langfuse.com:443x", "https://lf.example\t/x"],
)
def test_a_malformed_base_url_gives_no_project(base_url: str) -> None:
    env = {**_KEYS, "LANGFUSE_BASE_URL": base_url}
    assert target_langfuse_project(env) is None
