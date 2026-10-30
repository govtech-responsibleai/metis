"""The ``{{secret:NAME}}`` form: a login secret typed by code, never by the agent."""

from __future__ import annotations

import pytest

from metis.engine.simulation.runners.rules import ToolRefused
from metis.engine.simulation.runners.spans import secret_name

_ALLOWED = frozenset({"APP_USER", "APP_PASSWORD"})


def test_a_lone_secret_names_its_variable() -> None:
    assert secret_name("{{secret:APP_USER}}", _ALLOWED) == "APP_USER"


def test_text_without_a_secret_is_not_one() -> None:
    assert secret_name("hello {{1}}", _ALLOWED) is None


@pytest.mark.parametrize(
    "text",
    [
        "password {{secret:APP_USER}}",
        "{{secret:APP_USER}}{{secret:APP_PASSWORD}}",
        "{{secret:OTHER}}",
        "{{secret:app_user}}",
        "{{secret:}}",
    ],
)
def test_a_secret_must_stand_alone_and_be_one_the_binding_lists(text: str) -> None:
    with pytest.raises(ToolRefused, match="secret"):
        secret_name(text, _ALLOWED)
