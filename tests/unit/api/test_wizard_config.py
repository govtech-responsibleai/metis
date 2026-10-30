from __future__ import annotations

from fastapi.testclient import TestClient


def test_wizard_config_returns_package_owned_working_status(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/wizard/config")

    assert response.status_code == 200
    body = response.json()
    assert (
        body["opening_question"]
        == "Tell me about your product. What does it do, and who uses it?"
    )
    assert body["working_status"] == "Working on your Interview…"
    assert [item["id"] for item in body["perspectives"]] == [
        "end_user",
        "engineer",
        "compliance",
        "security",
    ]
    assert all(item["label"] and item["question"] for item in body["perspectives"])
    assert [category["id"] for category in body["capability_categories"]] == [
        "cognitive",
        "interaction",
        "operational",
    ]
    assert (
        sum(len(category["capabilities"]) for category in body["capability_categories"])
        == 12
    )
    assert body["document_limits"]["max_documents"] == 20
    assert body["document_limits"]["max_extraction_file_bytes"] == 10_000_000
    assert body["document_limits"]["max_text_characters_total"] == 1_000_000
    assert body["document_limits"]["extraction_extensions"] == [
        "csv",
        "docx",
        "json",
        "md",
        "pdf",
        "txt",
        "yaml",
        "yml",
    ]
