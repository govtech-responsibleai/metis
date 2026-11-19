""".env.example lists every variable that the shipped code reads.

The names come from three places: string literals in the shipped source that look like a METIS
setting, the variables of each model role, and the ``${NAME}`` references in shipped bindings.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from metis.core.model_settings import ROLES

ROOT = Path(__file__).resolve().parents[2]

SOURCE_ROOTS = (
    *sorted((ROOT / "packages").glob("*/src")),
    ROOT / "apps" / "api" / "src",
)

PREFIXES = (
    "METIS_",
    "LANGFUSE_",
    "OPENAI_",
    "INTERVIEW_",
    "EMBEDDING_",
    "USER_AGENT_",
    "RUNNER_AGENT_",
    "JUDGE_",
)
"""A string literal that starts with one of these is a setting, when it is a variable name."""

EXACT = frozenset({"DEFAULT_MODEL", "HOST", "PORT"})
"""Settings whose names have no METIS prefix."""

_VARIABLE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]+")
_REFERENCE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_LISTED = re.compile(r"^#? ?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _is_setting(text: str) -> bool:
    return bool(_VARIABLE.fullmatch(text)) and (
        text in EXACT or text.startswith(PREFIXES)
    )


def _literal_settings(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exported = {
        id(node)
        for assign in ast.walk(tree)
        if isinstance(assign, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__all__" for t in assign.targets)
        for node in ast.walk(assign.value)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in exported
        and _is_setting(node.value)
    }


def read_variables() -> set[str]:
    names: set[str] = set()
    for root in SOURCE_ROOTS:
        for path in root.rglob("*.py"):
            names |= _literal_settings(path)
        for pattern in ("*.yaml", "*.yml", "*.json"):
            for path in root.rglob(pattern):
                names |= set(_REFERENCE.findall(path.read_text(encoding="utf-8")))
    for spec in ROLES.values():
        names |= {spec.model_var, *spec.key_vars, *spec.url_vars}
    return names


def listed_variables() -> set[str]:
    return set(_LISTED.findall((ROOT / ".env.example").read_text(encoding="utf-8")))


def test_env_example_lists_every_variable_the_code_reads() -> None:
    missing = sorted(read_variables() - listed_variables())

    assert not missing, f"Add these to .env.example: {', '.join(missing)}"


def test_the_scan_finds_settings_from_each_source() -> None:
    names = read_variables()

    assert {"METIS_API_ENGINE_MAX_RUNS", "EMBEDDING_API_KEY", "TOYAPP_API_URL"} <= names
