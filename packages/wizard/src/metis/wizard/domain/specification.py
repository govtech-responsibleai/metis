"""Wizard persistence for the shared Specification contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pathlib import Path

import yaml

from metis.core.experiment import Persona as Persona
from metis.core.experiment import Scenario as Scenario
from metis.core.experiment import Task as Task
from metis.core.profile import Behaviour as Behaviour
from metis.core.profile import Criterion as Criterion
from metis.core.profile import Feature as Feature
from metis.core.profile import NamedNode as NamedNode
from metis.core.profile import Target as Target
from metis.core.specification import Specification as CoreSpecification
from metis.core.specification import (
    collect_specification_ids as collect_specification_ids,
)


class Specification(CoreSpecification):
    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def to_yaml(self) -> str:
        document = self.model_dump(mode="json")
        header = {
            key: document[key] for key in ("schema_version", "id", "runner_factory_ref")
        }
        return yaml.safe_dump(
            {**header, **document}, sort_keys=False, allow_unicode=True
        )

    def save(self, path: Path) -> None:
        path.write_text(self.to_yaml(), encoding="utf-8")
