"""Regenerate the golden specification file.

    uv run python tests/fixtures/wizard/regenerate_golden.py

Run this when the compiler or the fixture specification changes *on purpose*, then read the diff
before committing it. The golden file's whole job is to make an unintended change visible,
so regenerating without reading the diff throws away the only thing it was buying.
"""

import sys
from pathlib import Path

# Put the repo root on the path so `tests.fixtures.wizard` imports when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from metis.wizard.application.compile import compile_experiment, to_yaml  # noqa: E402
from tests.fixtures.wizard.specifications import research_assistant  # noqa: E402

EXPERIMENT_ID = "research-assistant"
GOLDEN = Path(__file__).parent / "golden_specification.yaml"


def main() -> None:
    document = compile_experiment(research_assistant(), EXPERIMENT_ID)
    GOLDEN.write_text(to_yaml(document))
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    main()
