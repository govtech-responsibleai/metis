"""The health probe: a container needs one cheap, unauthenticated liveness check."""

from __future__ import annotations

from fastapi.testclient import TestClient

from metis.api import __version__, core_version


def test_health_reports_ok_and_both_versions(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "core_version": core_version,
    }
