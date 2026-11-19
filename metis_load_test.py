"""Start N experiments at the same moment against a running METIS API, and say yes or no.

`make load-test LOAD_TEST_USERS=N` runs this module. It copies the input folder N times into the
project folder of the API, each copy with its own Specification id, so no two starts share an
experiment folder. Then N threads start behind one barrier. Every two seconds the module reads the
status of each experiment and prints one line for each. It ends when every experiment has ended,
or at the timeout.

The verdict is yes only when every start is accepted, every experiment ends `completed` with
phase `evaluating`, and the 95th percentile of the status route is under one second. Queue wait
and run time are reported for a person to judge, and they are not part of the verdict.

On Ctrl-C or a timeout, the module stops every experiment that it started and that is still
alive. The input copies and the experiment folders stay on disk.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

LOAD_TEST_DIR = Path("evaluations") / "load-test"

# The top-level `id:` of a specification.yaml. Indented ids (of features, behaviours, and so on)
# do not match, because the line must start with `id:`.
_TOP_LEVEL_ID = re.compile(r"^id:[ \t]*(?P<value>.*?)[ \t]*(?:#.*)?$", re.MULTILINE)


@dataclass(frozen=True)
class InputCopy:
    """One copy of the input folder, for one user."""

    user: int
    path: Path
    input_dir: str
    """The copy's path relative to the project folder, as the simulate route takes it."""


def _top_level_id(text: str) -> re.Match[str]:
    matches = list(_TOP_LEVEL_ID.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f"specification.yaml must have one top-level id line, found {len(matches)}"
        )
    return matches[0]


def rewrite_specification_id(text: str, new_id: str) -> str:
    """Return `text` with its top-level `id` set to `new_id`, and every other line unchanged.

    The change is made in the text, not through a YAML load and dump, so the copy keeps the
    layout and the comments of its source.
    """
    match = _top_level_id(text)
    return f"{text[: match.start()]}id: {json.dumps(new_id)}{text[match.end() :]}"


def _read_id(text: str) -> str:
    value = _top_level_id(text).group("value")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def make_input_copies(
    source: Path, project_dir: Path, users: int, *, stamp: str
) -> list[InputCopy]:
    """Copy `source` once for each user, under `evaluations/load-test/<stamp>/` of the project.

    Copy `i` is `<id>-load-<i>`, and its Specification id is the same text.

    :raises ValueError: `source` has no specification.yaml, or no single top-level id.
    :raises FileExistsError: the folder of `stamp` exists already.
    """
    spec_path = source / "specification.yaml"
    if not spec_path.is_file():
        raise ValueError(f"{source} has no specification.yaml")
    text = spec_path.read_text(encoding="utf-8")
    source_id = _read_id(text)

    relative_root = LOAD_TEST_DIR / stamp
    (project_dir / relative_root).mkdir(parents=True, exist_ok=False)
    copies: list[InputCopy] = []
    for user in range(1, users + 1):
        name = f"{source_id}-load-{user}"
        path = project_dir / relative_root / name
        shutil.copytree(source, path)
        (path / "specification.yaml").write_text(
            rewrite_specification_id(text, name), encoding="utf-8"
        )
        copies.append(
            InputCopy(user=user, path=path, input_dir=(relative_root / name).as_posix())
        )
    return copies
