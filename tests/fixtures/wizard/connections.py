"""Target binding values and connections for the connection tests. No real target is used."""

from __future__ import annotations

from typing import Any

import httpx

from metis.wizard.contracts import (
    ConnectionStatus,
    ConnectionTransport,
    TargetConnection,
)

# A value that must never appear in a state, a ZIP, a message, or a log.
PLANTED_SECRET = "sk-live-PLANTED-0123456789"


def http_binding(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "identity": {"name": "Policy assistant"},
        "transport": "http",
        "spec_url": "${APP_URL}/openapi.json",
        "auth": {"secret_env": "APP_KEY"},
        "forbidden_calls": ["DELETE /**"],
    }
    data.update(overrides)
    return data


def browser_binding(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "identity": {"name": "Policy assistant"},
        "transport": "browser",
        "start_url": "${APP_URL}/login",
        "login": {
            "note": "Type {{secret:APP_USER}} and {{secret:APP_PASSWORD}}, then sign in.",
            "secrets": ["APP_USER", "APP_PASSWORD"],
        },
    }
    data.update(overrides)
    return data


def connection(
    transport: ConnectionTransport = ConnectionTransport.HTTP,
    status: ConnectionStatus = ConnectionStatus.UNCHECKED,
) -> TargetConnection:
    binding = (
        http_binding() if transport is ConnectionTransport.HTTP else browser_binding()
    )
    return TargetConnection.model_validate(
        {"transport": transport, "binding": binding, "status": status}
    )


OPENAPI_DOCUMENT = {
    "openapi": "3.1.0",
    "info": {"title": "Policy assistant", "version": "1"},
    "servers": [{"url": "/api/v1"}],
    "paths": {"/chat": {"post": {}}},
}


# A chat target: one message write, plus writes that are not messages.
CHAT_DOCUMENT = {
    "openapi": "3.1.0",
    "info": {"title": "Policy assistant", "version": "1"},
    "servers": [{"url": "/api/v1"}],
    "paths": {
        "/conversations/{id}/messages": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Message"}
                        }
                    }
                }
            },
            "get": {},
        },
        "/settings": {
            "patch": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["theme", "language"],
                                "properties": {
                                    "theme": {"type": "string"},
                                    "language": {"type": "string"},
                                },
                            }
                        }
                    }
                }
            }
        },
        "/conversations/{id}/title": {
            "put": {
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["colour"],
                                "properties": {
                                    "colour": {"type": "string", "enum": ["red"]}
                                },
                            }
                        }
                    }
                }
            }
        },
        "/upload": {"post": {"requestBody": {"content": {"multipart/form-data": {}}}}},
    },
    "components": {
        "schemas": {
            "Message": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "draft": {"type": "boolean"},
                },
            }
        }
    },
}


def mock_client_factory(handler):
    """Build the check's HTTP client on `httpx.MockTransport`, so no request leaves the test."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(tls_verify: bool) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(record))

    factory.requests = seen  # type: ignore[attr-defined]
    return factory
