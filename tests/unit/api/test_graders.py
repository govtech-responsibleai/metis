from __future__ import annotations

from fastapi.testclient import TestClient


def test_grader_catalogue_marks_only_the_criterion_judge_as_description_driven(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/graders")

    assert response.status_code == 200
    driven = [
        row["fqn"] for row in response.json() if row["uses_criterion_description"]
    ]
    assert driven == ["metis.library.graders.CriterionJudgeGrader"]
    assert "metis.library.graders.ErrorRecoveryGrader" in [
        row["fqn"] for row in response.json()
    ]


def test_grader_catalogue_is_sorted_and_has_only_display_fields(
    client: TestClient, a_catalogued_grader: type
) -> None:
    response = client.get("/api/v1/graders")

    assert response.status_code == 200
    rows = response.json()
    assert rows == sorted(rows, key=lambda row: row["fqn"])
    assert rows
    assert all(
        set(row)
        == {
            "fqn",
            "name",
            "description",
            "uses_criterion_description",
            "settings",
            "taxonomy",
            "dimension",
        }
        for row in rows
    )


def test_grader_catalogue_rows_carry_the_taxonomy_dimension_and_settings(
    client: TestClient,
) -> None:
    rows = {row["fqn"]: row for row in client.get("/api/v1/graders").json()}

    recovery = rows["metis.library.graders.ErrorRecoveryGrader"]
    assert recovery["dimension"] == "execution_and_decision_quality"
    assert recovery["taxonomy"]["measure"] == "error_recovery"
    assert recovery["taxonomy"]["scopes"] == ["session"]
    assert recovery["taxonomy"]["grader_types"] == ["llm"]
    settings = {setting["name"]: setting for setting in recovery["settings"]}
    assert settings["scope"]["choices"] == ["session"]
    assert settings["threshold"] == {
        "name": "threshold",
        "kind": "number",
        "required": False,
        "default": 0.5,
        "choices": [],
        "base": True,
        "description": None,
    }
    judge = rows["metis.library.graders.CriterionJudgeGrader"]
    assert judge["dimension"] is None


def test_grader_catalogue_failure_uses_service_error_shape(
    client: TestClient,
    monkeypatch,
) -> None:
    import metis.api.routes.graders as graders_routes

    monkeypatch.setattr(
        graders_routes,
        "grader_catalogue",
        lambda: (_ for _ in ()).throw(RuntimeError("broken")),
    )
    response = client.get("/api/v1/graders")

    assert response.status_code == 500
    assert response.json() == {
        "type": "failure",
        "code": "internal_error",
        "message": "The grader catalogue could not be loaded.",
        "retryable": False,
    }
