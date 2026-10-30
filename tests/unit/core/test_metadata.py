"""Optional metadata in Specification documents."""

import pytest
from pydantic import ValidationError

from metis.core.experiment import Persona, Scenario
from metis.core.specification import Specification


@pytest.mark.parametrize(
    "model, field", [(Persona, "personas"), (Scenario, "scenarios")]
)
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"metadata": {}},
        {"metadata": {"custom_key": "Custom context", "another key": ""}},
    ],
)
def test_metadata_survives_specification_round_trip(model, field, fields):
    record = model(
        id="item-1", name="Example", description="Existing description", **fields
    )
    specification = Specification.model_validate(
        {
            "target": {
                "name": "Example",
                "users": "Users",
                "description": "Help users",
            },
            field: [record],
        }
    )
    restored = Specification.model_validate_json(specification.model_dump_json())
    result = getattr(restored, field)[0]
    assert result.metadata == fields.get("metadata", {})
    assert result.description == "Existing description"


@pytest.mark.parametrize("model", [Persona, Scenario])
@pytest.mark.parametrize("value", [None, 42, 1.5, True, [], {}, {"nested": "text"}])
def test_metadata_values_must_be_strings(model, value):
    with pytest.raises(ValidationError):
        model(
            id="item-1",
            name="Example",
            description="Description",
            metadata={"custom": value},
        )
