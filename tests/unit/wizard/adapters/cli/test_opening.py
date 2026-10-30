"""The CLI interview-opening fields."""

from metis.wizard.adapters.cli.opening import (
    read_capability_evidence,
    read_description,
)
from metis.wizard.application.config import load_config


def test_capability_input_shows_the_catalogue_and_reads_selection_and_confidence() -> (
    None
):
    replies = iter(["1, Tool Use", "medium"])
    out: list[str] = []

    selected, confidence = read_capability_evidence(
        out=out.append, read=lambda _: next(replies)
    )

    assert [item.value for item in selected] == [
        "planning_goal_management",
        "tool_use",
    ]
    assert confidence.value == "medium"
    text = "\n".join(out)
    assert all(
        category in text for category in ("Cognitive", "Interaction", "Operational")
    )
    assert all(
        label in text
        for label in (
            "Planning & Goal Management",
            "Tool Use",
            "System Management",
        )
    )


def test_run_mode_takes_the_binding_from_the_cli_or_from_a_file(tmp_path) -> None:
    from metis.wizard.adapters.cli.connection import read_binding_source

    def ask(*answers: str):
        replies = iter(answers)
        return read_binding_source(
            out=lambda _line: None, read=lambda _p: next(replies)
        )

    assert ask("") is None
    binding = tmp_path / "binding.yaml"
    binding.write_text("schema_version: 1\n")
    assert ask("2", str(tmp_path / "absent.yaml"), str(binding)) == binding


def test_description_input_asks_the_opening_question_until_it_gets_an_answer() -> None:
    replies = iter(["   ", "  A research assistant that cites sources.  "])
    asked: list[str] = []
    out: list[str] = []

    def read(prompt: str) -> str:
        asked.append(prompt)
        return next(replies)

    description = read_description(out=out.append, read=read)

    assert description == "A research assistant that cites sources."
    assert asked == ["> ", "> "]
    # the question is the body of the step header, shown once above the prompt
    assert load_config().opening_question in out[0]
    assert out[1:] == ["  Enter a description of the target."]


def test_skipping_capability_evidence_does_not_ask_for_confidence() -> None:
    assert read_capability_evidence(out=lambda _: None, read=lambda _: "skip") == (
        None,
        None,
    )


def test_run_mode_offers_the_suggested_message_calls_and_uses_them_only_on_yes() -> (
    None
):
    import httpx

    from metis.wizard.adapters.cli.connection import read_target_connection
    from tests.fixtures.wizard.connections import (
        CHAT_DOCUMENT,
        http_binding,
        mock_client_factory,
    )

    factory = mock_client_factory(
        lambda request: (
            httpx.Response(200, json=CHAT_DOCUMENT)
            if request.method == "GET"
            else httpx.Response(200)
        )
    )
    environ = {"APP_URL": "https://app.example", "APP_KEY": "key"}

    def run(*answers: str):
        replies = iter(answers)
        out: list[str] = []
        connection = read_target_connection(
            out=out.append,
            read=lambda _prompt: next(replies),
            values=http_binding(submissions=["POST /chats"]),
            environ=environ,
            client_factory=factory,
        )
        return connection, "\n".join(out)

    declined, text = run("n", "c")
    assert "⚠ POST /chats matches no call in the OpenAPI document." in text
    assert "  POST /conversations/*/messages" in text
    assert declined is not None
    assert declined.binding.submissions == ["POST /chats"]

    accepted, _ = run("y", "c")
    assert accepted is not None
    assert accepted.binding.submissions == ["POST /conversations/*/messages"]
