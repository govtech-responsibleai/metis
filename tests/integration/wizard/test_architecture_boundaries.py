"""Guard the ownership boundaries that make the wizard adapters extractable."""

from __future__ import annotations

import ast
from pathlib import Path

import metis.wizard

# Walk the installed wizard source, so the guard follows the package wherever it lives.
SRC = Path(metis.wizard.__file__).resolve().parent


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_shared_layers_only_depend_inward() -> None:
    allowed = {
        "domain": {"domain"},
        "contracts": {"domain", "contracts"},
        "application": {"domain", "contracts", "application"},
    }
    forbidden_ui = {"typer", "rich", "fastapi", "playwright", "selenium"}

    for layer, dependencies in allowed.items():
        root = SRC / layer
        for path in root.rglob("*.py"):
            for imported in _imports(path):
                if imported in forbidden_ui or imported.startswith(
                    tuple(f"{name}." for name in forbidden_ui)
                ):
                    raise AssertionError(f"{path} imports UI dependency {imported}")
                prefix = "metis.wizard."
                if not imported.startswith(prefix):
                    continue
                imported_layer = imported[len(prefix) :].split(".", 1)[0]
                if imported_layer not in dependencies:
                    raise AssertionError(
                        f"{path.relative_to(SRC)} imports {imported}; "
                        f"{layer} may only depend on {sorted(dependencies)}"
                    )


def test_adapters_do_not_import_sibling_adapters() -> None:
    for adapter in ("cli", "llm", "web"):
        root = SRC / "adapters" / adapter
        for path in root.rglob("*.py"):
            for imported in _imports(path):
                if imported.startswith("metis.wizard.adapters."):
                    imported_adapter = imported.split(".")[3]
                    if imported_adapter != adapter:
                        raise AssertionError(
                            f"{path.relative_to(SRC)} imports sibling adapter {imported}"
                        )


def test_langfuse_is_only_imported_by_the_llm_adapter() -> None:
    """Tracing now rides on the drop-in client in the gateway, so the SDK may appear anywhere
    under adapters/llm — but nowhere else. The shared layers stay tracing-free."""
    for path in SRC.rglob("*.py"):
        for imported in _imports(path):
            if imported == "langfuse" or imported.startswith("langfuse."):
                assert path.is_relative_to(SRC / "adapters" / "llm"), (
                    f"{path.relative_to(SRC)} imports the tracing SDK; "
                    "only adapters/llm may"
                )


def test_bootstrap_is_the_only_adapter_composition_root() -> None:
    for path in SRC.rglob("*.py"):
        if path == SRC / "bootstrap.py":
            continue
        adapters = {
            imported.split(".")[3]
            for imported in _imports(path)
            if imported.startswith("metis.wizard.adapters.")
        }
        assert len(adapters) <= 1, (
            f"{path.relative_to(SRC)} composes {sorted(adapters)}"
        )


def test_implementation_paths_follow_the_ownership_layout() -> None:
    for name in (
        "models",
        "interview",
        "steps",
        "compile",
        "matching",
        "door",
        "cli.py",
    ):
        assert not (SRC / name).exists(), f"unowned implementation path remains: {name}"
