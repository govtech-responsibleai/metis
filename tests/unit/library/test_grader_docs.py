"""The grader pages and data on the docs site match the grader catalogue."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GENERATOR = ROOT / "packages" / "library" / "scripts" / "generate_grader_docs.py"


def test_grader_docs_match_the_catalogue() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
