"""Direct assessment editing with fields from the selected grader schema."""

from __future__ import annotations

import json
from importlib import import_module
from typing import TYPE_CHECKING, Any

from metis.library.grader import CriterionJudgeArgs, JudgeArgs
from metis.wizard.contracts.conversation import FormChoice, FormField

if TYPE_CHECKING:
    from metis.wizard.domain.specification import Criterion


def settings_fields(criterion: Criterion) -> list[FormField]:
    if not criterion.grader_fqn:
        return []
    module, name = criterion.grader_fqn.rsplit(".", 1)
    model = getattr(import_module(module), name).args_model
    schema = model.model_json_schema()
    fields = []
    for name, prop in schema["properties"].items():
        if name == "criterion" and issubclass(model, CriterionJudgeArgs):
            continue
        if name == "max_input_tokens" and issubclass(model, JudgeArgs):
            continue
        if "$ref" in prop:
            prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[-1]]
        kind = prop.get("type")
        nullable = False
        if "anyOf" in prop:
            variants = prop["anyOf"]
            nullable = any(v.get("type") == "null" for v in variants)
            prop = next((v for v in variants if v.get("type") != "null"), prop)
            if "$ref" in prop:
                prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[-1]]
            kind = prop.get("type")
        if kind not in {"string", "integer", "number", "boolean"}:
            raise ValueError(
                f"The {name} setting cannot be edited in this form. Use a grader with text, number, or boolean settings."
            )
        value = criterion.grader_args.get(
            name, prop.get("default", schema["properties"][name].get("default"))
        )
        fields.append(
            FormField(
                id=f"args.{name}",
                label=prop.get("title", name),
                input_type=kind,
                multiline=False,
                value=""
                if value is None
                else str(value).lower()
                if isinstance(value, bool)
                else str(value),
                required=name in schema.get("required", [])
                and not nullable
                and not (name == "model" and issubclass(model, JudgeArgs)),
                choices=[
                    FormChoice(value=text, label=text)
                    for text in (
                        str(v).lower() if isinstance(v, bool) else str(v)
                        for v in prop.get("enum", [])
                    )
                ],
                help=prop.get("description", ""),
                group="Grader settings",
            )
        )
    return fields


def settings_values(
    fields: list[FormField], values: dict[str, str], previous: dict[str, Any]
) -> dict[str, Any]:
    result = dict(previous)
    for field in fields:
        if not field.id.startswith("args."):
            continue
        if field.id not in values:
            continue
        name = field.id.removeprefix("args.")
        value = values.get(field.id, field.value)
        if not value and not field.required:
            result.pop(name, None)
        elif field.input_type == "string":
            result[name] = value
        else:
            result[name] = json.loads(value)
    return result
