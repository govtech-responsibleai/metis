"""Generate and check the published JSON Schemas owned by core."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from metis.core.console import console
from metis.core.specification import _SPECIFICATION_VERSION, Specification
from metis.core.target_binding import _TARGET_BINDING_VERSION, TargetBinding

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
REPO_ROOT = SCHEMA_DIR.parents[2]

_MODELS = [
    (Specification, "specification.schema.json", _SPECIFICATION_VERSION, False),
    (TargetBinding, "target-binding.schema.json", _TARGET_BINDING_VERSION, False),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check without writing files"
    )
    args = parser.parse_args()
    errors: list[str] = []
    if args.check:
        published = (
            subprocess.check_output(
                [
                    "git",
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "--",
                    "*.schema.json",
                ],
                cwd=REPO_ROOT,
            )
            .decode()
            .split("\0")
        )
        expected = {
            (SCHEMA_DIR / filename).relative_to(REPO_ROOT).as_posix()
            for _, filename, _, _ in _MODELS
        }
        for filename in sorted(set(published) - expected - {""}):
            if (REPO_ROOT / filename).is_file():
                errors.append(
                    f"Unregistered schema: {filename}. Publish schemas through core."
                )
    else:
        SCHEMA_DIR.mkdir(exist_ok=True)
    for model, filename, version, by_alias in _MODELS:
        schema = model.model_json_schema(by_alias=by_alias)
        schema["title"] = f"{model.__name__} v{version}"
        out = SCHEMA_DIR / filename
        content = json.dumps(schema, indent=2) + "\n"
        if args.check:
            if not out.is_file() or out.read_text(encoding="utf-8") != content:
                errors.append(
                    f"Schema missing or stale: {filename}. Run make -C packages/core generate-schema."
                )
        else:
            out.write_text(content, encoding="utf-8")
            console.print(f"Written: {out}")
    if errors:
        for error in errors:
            console.print(error)
        raise SystemExit(1)
    if args.check:
        console.print("Schemas OK")


if __name__ == "__main__":
    main()
