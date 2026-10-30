"""The trace processor's readers: the only code that reads input/output/metadata (#431).

One test per supported shape, plus every way a payload can fail to be read. A reader returns
a value or a Problem, never both and never an exception.
"""

from __future__ import annotations

from metis.core.trace_processing import (
    Message,
    Problem,
    ToolCallPart,
    messages_of,
    text_of,
    tool_arguments,
    tool_result,
)
from metis.core.traces import Observation


def _tool(**fields: object) -> Observation:
    return Observation(id="o9", trace_id="t3", type="TOOL", **fields)  # type: ignore[arg-type]


class TestTextOf:
    def test_plain_string_is_text_for_any_role(self) -> None:
        assert text_of("hello", role="user") == "hello"
        assert text_of("hello", role="assistant") == "hello"

    def test_openai_messages_last_message_of_role(self) -> None:
        value = {
            "messages": [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ]
        }
        assert text_of(value, role="user") == "q2"
        assert text_of(value, role="assistant") == "a1"

    def test_bare_message_list_is_read(self) -> None:
        """A model call's output can be a list with no ``messages`` wrapper."""
        assert (
            text_of([{"role": "assistant", "content": "done"}], role="assistant")
            == "done"
        )

    def test_a_single_message_is_read(self) -> None:
        assert text_of({"role": "user", "content": "hi"}, role="user") == "hi"

    def test_content_blocks_are_joined(self) -> None:
        value = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b"},
                ],
            }
        ]
        assert text_of(value, role="assistant") == "a\nb"

    def test_no_message_with_the_role_is_missing(self) -> None:
        problem = text_of([{"role": "system", "content": "s"}], role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "missing"

    def test_none_is_missing(self) -> None:
        problem = text_of(None, role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "missing"

    def test_unknown_shape_is_unsupported(self) -> None:
        problem = text_of({"foo": 1}, role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"
        assert "foo" in problem.detail

    def test_a_number_is_unsupported(self) -> None:
        problem = text_of(42, role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"
        assert "int" in problem.detail


class TestMessagesOf:
    def test_otel_genai_parts_are_joined(self) -> None:
        value = [
            {
                "role": "assistant",
                "parts": [
                    {"type": "text", "content": "a"},
                    {"type": "tool_call", "name": "search", "arguments": {"q": "x"}},
                    {"type": "text", "content": "b"},
                ],
            }
        ]
        result = messages_of(value)
        assert not isinstance(result, Problem)
        (message,) = result
        assert message.text == "a\nb"
        assert message.tool_calls == (
            ToolCallPart(name="search", arguments={"q": "x"}),
        )

    def test_openai_tool_calls_are_read(self) -> None:
        value = {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"function": {"name": "lookup", "arguments": '{"id": 1}'}}
                    ],
                }
            ]
        }
        result = messages_of(value)
        assert result == (
            Message(
                role="assistant",
                text="",
                tool_calls=(ToolCallPart(name="lookup", arguments='{"id": 1}'),),
            ),
        )

    def test_a_list_holding_a_non_message_is_unsupported(self) -> None:
        problem = messages_of([{"role": "user", "content": "q"}, 3])
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"


class TestTools:
    def test_tool_arguments_need_a_dict(self) -> None:
        assert tool_arguments(_tool(input={"code": "1"})) == {"code": "1"}
        problem = tool_arguments(_tool(input="x"))
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"

    def test_python_syntax_string_stays_text(self) -> None:
        """Some tool outputs look like dicts but are Python syntax. Never parsed."""
        raw = "{'_type': 'form_request', 'id': 'f1'}"
        assert tool_result(_tool(output=raw)) == raw

    def test_a_structured_result_is_returned_as_is(self) -> None:
        assert tool_result(_tool(output={"ok": True})) == {"ok": True}

    def test_problems_name_their_observation(self) -> None:
        problem = tool_arguments(_tool(input=None))
        assert isinstance(problem, Problem)
        assert (
            problem.kind,
            problem.trace_id,
            problem.observation_id,
            problem.field,
        ) == (
            "missing",
            "t3",
            "o9",
            "input",
        )

    def test_json_payloads_are_shown_as_recorded(self) -> None:
        arguments = '{"amount": 10.50}'
        result = '[\n  {"price": 10.50}\n]'
        call = _tool(input=arguments, output=result)
        assert tool_arguments(call) == arguments
        assert tool_result(call) == result

    def test_a_missing_result_is_missing(self) -> None:
        problem = tool_result(_tool(output=None))
        assert isinstance(problem, Problem)
        assert (problem.kind, problem.field) == ("missing", "output")


class TestNonTextParts:
    """Image and file parts are not supported: they must not read as an empty reply (#431)."""

    def test_an_otel_message_with_only_an_image_part_is_unsupported(self) -> None:
        value = [
            {
                "role": "user",
                "parts": [{"type": "blob", "modality": "image", "content": "x"}],
            }
        ]
        problem = text_of(value, role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"

    def test_an_openai_message_with_only_an_image_block_is_unsupported(self) -> None:
        value = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "u"}}],
            }
        ]
        problem = text_of(value, role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"

    def test_parts_that_are_not_objects_are_unsupported(self) -> None:
        problem = text_of([{"role": "user", "parts": ["junk"]}], role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"

    def test_text_beside_an_image_is_still_read(self) -> None:
        value = [
            {
                "role": "user",
                "parts": [
                    {"type": "text", "content": "see this"},
                    {"type": "blob", "content": "x"},
                ],
            }
        ]
        assert text_of(value, role="user") == "see this"


class TestLangfuseMediaReferences:
    """Langfuse replaces uploaded media with a reference token. METIS can't show it to a judge,
    so a payload holding one is reported, never read as text (#431)."""

    TOKEN = "@@@langfuseMedia:type=image/jpeg|id=abc-123|source=bytes@@@"

    def test_a_reply_that_is_a_media_reference_is_unsupported(self) -> None:
        problem = text_of(self.TOKEN, role="assistant")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"
        assert "image/jpeg" in problem.detail

    def test_text_that_embeds_a_media_reference_is_unsupported(self) -> None:
        problem = text_of(f"Here is the chart: {self.TOKEN}", role="assistant")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"

    def test_a_message_holding_a_media_reference_is_unsupported(self) -> None:
        value = [{"role": "user", "content": f"see {self.TOKEN}"}]
        problem = text_of(value, role="user")
        assert isinstance(problem, Problem)
        assert problem.kind == "unsupported"

    def test_a_tool_result_holding_a_media_reference_is_unsupported(self) -> None:
        problem = tool_result(_tool(output=self.TOKEN))
        assert isinstance(problem, Problem)
        assert (problem.kind, problem.field) == ("unsupported", "output")

    def test_ordinary_text_with_at_signs_is_still_text(self) -> None:
        assert (
            text_of("email me @ noon @@ later", role="user")
            == "email me @ noon @@ later"
        )
