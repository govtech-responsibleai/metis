"""Read use cases from the shared input and output folder layout."""

from pathlib import Path

from metis.testbed.contracts import CaseConfig


def load_case(evals_root: Path, relative: str) -> tuple[CaseConfig, Path]:
    """Find the prompt and supporting documents without exposing the reference."""
    root = (evals_root / relative).resolve()
    if not root.is_relative_to(evals_root.resolve()) or root == evals_root.resolve():
        raise ValueError(f"Use case is outside the evaluation folder: {relative}")
    if not root.is_dir():
        raise FileNotFoundError(root)
    inputs = []
    for path in sorted((root / "inputs").rglob("*")):
        if not path.is_file() or any(
            part.startswith(".") for part in path.relative_to(root).parts
        ):
            continue
        if not path.resolve().is_relative_to((root / "inputs").resolve()):
            raise ValueError(f"Input is outside the input folder: {path}")
        inputs.append(path.relative_to(root).as_posix())
    return CaseConfig(
        id=root.name,
        component="wizard",
        inputs=inputs,
        expected_output="outputs/specification.yaml",
    ), root
