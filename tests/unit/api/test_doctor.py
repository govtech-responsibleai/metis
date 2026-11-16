"""`GET /api/v1/doctor`: the checks of `metis doctor`, with the network checks faked."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metis.core import doctor
from metis.core.doctor import DoctorResult, DoctorStatus

if TYPE_CHECKING:
    import pytest
    from fastapi.testclient import TestClient


def test_the_doctor_route_returns_each_check_in_display_order(
    engine_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        doctor,
        "check_gateway",
        lambda env: DoctorResult("Gateway", DoctorStatus.PASS, "reached"),
    )
    monkeypatch.setattr(
        doctor,
        "check_langfuse",
        lambda env: DoctorResult(
            "Langfuse", DoctorStatus.FAIL, "unreachable", "Check LANGFUSE_BASE_URL."
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    expected = doctor.run_doctor()

    response = engine_client.get("/api/v1/doctor")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": result.name,
            "status": str(result.status),
            "detail": result.detail,
            "fix": result.fix,
        }
        for result in expected
    ]
    assert response.json()[-2:] == [
        {"name": "Gateway", "status": "pass", "detail": "reached", "fix": None},
        {
            "name": "Langfuse",
            "status": "fail",
            "detail": "unreachable",
            "fix": "Check LANGFUSE_BASE_URL.",
        },
    ]
