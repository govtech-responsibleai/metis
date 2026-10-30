"""Generate and check the grader pages and the grader data that the docs site reads.

Each grader page, ``website/docs/library/<slug>.mdx``, shows the grader's taxonomy tags, the
first paragraph of its class docstring, the open-source prompt that it adapts, and the source
of its arguments and its ``criteria()`` prompt. The grader table and the sidebar render from
``website/src/data/graders.json``. The "Adapted from" links come from the grader catalogue,
``metis/library/graders/README.md``. Run this script after any change to a grader or to its
catalogue row.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import metis.library.graders as catalogue
from metis.core.console import console
from metis.library.grader import Grader, GraderArgs, JudgeArgs
from metis.library.taxonomy import Measure

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "website" / "src" / "data" / "graders.json"
PAGES = REPO_ROOT / "website" / "docs" / "library"
CATALOGUE = Path(catalogue.__file__).parent / "README.md"

_GROUPS = {
    "task_and_output_quality": "Task and Output Quality",
    "execution_and_decision_quality": "Execution and Decision Quality",
    "reliability_and_robustness": "Reliability and Robustness",
    "interaction_quality": "Interaction Quality",
}
_FALLBACK_GROUP = "Fallback judge"
_COMMON_ARGS = (BaseModel, GraderArgs, JudgeArgs)


def _group(grader: type[Grader[Any]]) -> str:
    if grader.taxonomy.measure is None:
        return _FALLBACK_GROUP
    package = grader.__module__.split(".")[-2]
    if package not in _GROUPS:
        raise SystemExit(f"Add a group title for {package!r} to _GROUPS.")
    return _GROUPS[package]


def _slug(grader: type[Grader[Any]]) -> str:
    return re.sub(
        r"(?<!^)(?=[A-Z])", "-", grader.__name__.removesuffix("Grader")
    ).lower()


def _title(grader: type[Grader[Any]]) -> str:
    measure = grader.taxonomy.measure
    words = measure.value if measure else _slug(grader)
    return re.sub(r"[_-]", " ", words).capitalize()


def _adapted_from() -> dict[str, str]:
    """The "Adapted from" cell of each grader's row in the grader catalogue README."""
    rows = re.findall(
        r"^\| `(\w+Grader)` \| (.+) \|$",
        CATALOGUE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return dict(rows)


def _docstring(grader: type[Grader[Any]]) -> str:
    """The first paragraph of the grader's class docstring."""
    first = inspect.cleandoc(grader.__doc__ or "").split("\n\n")[0]
    prose = re.sub(r"``([^`]+)``", r"`\1`", " ".join(first.split()))
    return prose.replace("{", "\\{").replace("<", "&lt;")


def _description(grader: type[Grader[Any]]) -> str:
    first = " ".join(inspect.cleandoc(grader.__doc__ or "").split("\n\n")[0].split())
    first = re.split(r"(?<=\.)\s", first)[0].removeprefix("Assess ")
    return re.sub(r"``([^`]+)``", r"\1", first[0].upper() + first[1:])


def _fields_only(cls: type) -> str:
    """The source of a model class with only its header, its fields, and their docstrings."""
    source = textwrap.dedent(inspect.getsource(cls))
    lines = source.splitlines()
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    kept = lines[node.lineno - 1 : node.body[0].lineno - 1]
    for index, stmt in enumerate(node.body):
        is_field = isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        is_field_doc = (
            index > 0
            and isinstance(node.body[index - 1], ast.AnnAssign)
            and isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
        if is_field or is_field_doc:
            kept += lines[stmt.lineno - 1 : stmt.end_lineno]
    if len(kept) == node.body[0].lineno - node.lineno:
        kept.append("    pass")
    return "\n".join(kept)


def _prompt(grader: type[Grader[Any]]) -> str:
    """The grader's class header, its ``criteria()`` method, and the helpers that it calls."""
    source = inspect.getsource(grader)
    node = ast.parse(textwrap.dedent(source)).body[0]
    assert isinstance(node, ast.ClassDef)
    header = textwrap.dedent(source).splitlines()[
        node.lineno - 1 : node.body[0].lineno - 1
    ]
    methods, pending = [], ["criteria"]
    while pending:
        name = pending.pop(0)
        if name in methods:
            continue
        methods.append(name)
        pending += re.findall(
            r"self\.(_\w+)\(", inspect.getsource(getattr(grader, name))
        )
    bodies = [inspect.getsource(getattr(grader, name)).rstrip() for name in methods]
    used = set(re.findall(r"\b(_[A-Z][A-Z0-9_]+)\b", "\n".join(bodies)))
    module_source = inspect.getsource(sys.modules[grader.__module__])
    module_lines = module_source.splitlines()
    constants = [
        "\n".join(module_lines[stmt.lineno - 1 : stmt.end_lineno])
        for stmt in ast.parse(module_source).body
        if isinstance(stmt, ast.Assign | ast.AnnAssign)
        and any(
            isinstance(target, ast.Name) and target.id in used
            for target in (
                stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            )
        )
    ]
    grader_class = "\n".join(header) + "\n" + "\n\n".join(bodies)
    return "\n\n".join([*constants, grader_class])


def _arguments(grader: type[Grader[Any]]) -> str:
    """The fields of the grader's arguments model and of the scope and task models it extends."""
    models = [
        cls
        for cls in reversed(grader.args_model.__mro__)
        if isinstance(cls, type)
        and issubclass(cls, BaseModel)
        and cls not in _COMMON_ARGS
        and "__annotations__" in vars(cls)
    ]
    return "\n\n\n".join(map(_fields_only, models))


def _page(grader: type[Grader[Any]], adapted_from: str) -> str:
    source = Path(inspect.getfile(grader)).resolve().relative_to(REPO_ROOT).as_posix()
    parts = [
        "---",
        f"title: {json.dumps(_title(grader))}",
        f"description: {json.dumps(_description(grader))}",
        "---",
        "",
        f"{{/* Generated from {source} by make generate-grader-docs. Do not edit. */}}",
        "",
        "import {GraderCode, GraderTags} from '@site/src/components/Graders';",
        "",
        f'<GraderTags name="{grader.__name__}" />',
        "",
        _docstring(grader),
        "",
    ]
    if adapted_from != "METIS":
        parts += [f"Adapted from {adapted_from}.", ""]
    parts += [
        "<GraderCode>",
        "",
        "```python",
        "\n\n\n".join(filter(None, [_arguments(grader), _prompt(grader)])),
        "```",
        "",
        "</GraderCode>",
        "",
    ]
    return "\n".join(parts)


def build() -> tuple[dict[str, Any], dict[Path, str]]:
    """The grader data and the content of each grader page."""
    measures = list(Measure)
    adapted_from = _adapted_from()
    graders = sorted(
        (
            cls
            for cls in vars(catalogue).values()
            if isinstance(cls, type) and issubclass(cls, Grader)
        ),
        key=lambda cls: (
            cls.taxonomy.measure is None,
            measures.index(cls.taxonomy.measure) if cls.taxonomy.measure else 0,
        ),
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    pages: dict[Path, str] = {}
    for grader in graders:
        taxonomy = grader.taxonomy
        if taxonomy.measure is None:
            source = "METIS"
        elif grader.__name__ in adapted_from:
            source = adapted_from[grader.__name__]
        else:
            raise SystemExit(
                f"{grader.__name__} has no row in {CATALOGUE.relative_to(REPO_ROOT)}."
            )
        slug = _slug(grader)
        pages[PAGES / f"{slug}.mdx"] = _page(grader, source)
        groups.setdefault(_group(grader), []).append(
            {
                "name": grader.__name__,
                "fqn": f"{catalogue.__name__}.{grader.__name__}",
                "slug": slug,
                "source_file": Path(inspect.getfile(grader))
                .resolve()
                .relative_to(REPO_ROOT)
                .as_posix(),
                "adapted_from": source,
                "taxonomy": {
                    "measure": taxonomy.measure.value if taxonomy.measure else None,
                    "scopes": [v.value for v in taxonomy.scopes],
                    "grader_types": [v.value for v in taxonomy.grader_types],
                    "reference_types": [v.value for v in taxonomy.reference_types],
                    "judgment_forms": [v.value for v in taxonomy.judgment_forms],
                    "aggregations": [v.value for v in taxonomy.aggregations],
                },
            }
        )
    data = {
        "groups": [
            {"title": title, "graders": items} for title, items in groups.items()
        ]
    }
    return data, pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check without writing files"
    )
    args = parser.parse_args()
    data, pages = build()
    outputs = {DATA: json.dumps(data, indent=2, ensure_ascii=False) + "\n", **pages}
    stale = sorted(set(PAGES.glob("*.mdx")) - set(pages))
    if args.check:
        problems = [
            path
            for path, content in outputs.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ] + stale
        for path in problems:
            console.print(f"Missing or stale: {path.relative_to(REPO_ROOT)}")
        if problems:
            console.print("Run make generate-grader-docs.")
            raise SystemExit(1)
        console.print("Grader docs OK")
        return
    for path in stale:
        path.unlink()
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    console.print(f"Written: {len(outputs)} files, removed {len(stale)}")


if __name__ == "__main__":
    main()
