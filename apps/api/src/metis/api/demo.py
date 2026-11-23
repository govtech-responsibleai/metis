"""The demo Target that each new user account gets.

The demo Target is the toy app, the Northstar Policy & Report Assistant. It has a done
Interview, its Specification and Target binding, and one finished Experiment with its report.
The files are in `demo_target/`, in the same layout as a project folder.
`apps/api/scripts/build_demo_target.py` builds them from the engine example
`http-agentic_eval_toyapp-workshop-lite` and one Experiment of it.

A user account gets its own copy one time, when the API makes the account. The copy is an
ordinary Target after that, so the user can change it or delete it, and a deleted demo does not
come back.
"""

from __future__ import annotations

import io
import json
import mimetypes
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from metis.api.records import (
    FileRef,
    InterviewRecord,
)
from metis.api.store import FILES, LOCAL_USER_ID, Store, Upload
from metis.api.tables import users
from metis.core import execution_layout, project_layout
from metis.wizard import InterviewStep

DEMO_FILES = Path(__file__).parent / "demo_target"
"""The folder of the demo files."""
INTERVIEW = Path(project_layout.INTERVIEWS) / "demo"
"""The folder of the demo Interview: its documents and `interview.json`."""
RECORD = Path("interview.json")
"""The title, the state and the transcript of the demo Interview, in its folder."""
EXPERIMENTS = Path(project_layout.EXPERIMENTS)
"""The folder that holds the one Experiment folder of the demo."""

_REPORT_ORDER = (
    execution_layout.RESULTS,
    execution_layout.REPORT_JSON,
    execution_layout.REPORT_HTML,
)
"""The report files, oldest first. A report that is older than its results is built again, so the
copy touches them in this order and keeps the report that the build script made."""


def add_demo_target(store: Store) -> str:
    """Give the user account of ``store`` its own demo Target. Return the Target id."""
    now = datetime.now()
    target_id = f"{now:%Y%m%d-%H%M%S}-interview-{secrets.token_hex(4)}"
    saved = json.loads((DEMO_FILES / INTERVIEW / RECORD).read_text(encoding="utf-8"))
    documents = sorted((DEMO_FILES / INTERVIEW / FILES).iterdir())
    record = InterviewRecord(
        id=target_id,
        title=saved["title"],
        stage=InterviewStep.DONE,
        created_at=round(now.timestamp() * 1000),
        updated_at=round(now.timestamp() * 1000),
        state=saved["state"],
        transcript=saved["transcript"],
        fixtures=[
            FileRef(
                name=path.name,
                type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                size=path.stat().st_size,
            )
            for path in documents
        ],
    )
    store.put_interview(
        target_id,
        record,
        [
            Upload(name=path.name, stream=io.BytesIO(path.read_bytes()))
            for path in documents
        ],
    )
    for source in sorted((DEMO_FILES / EXPERIMENTS).iterdir()):
        # The name of an Experiment folder is `<Target id>-<time>`. Keep the time of the demo.
        started = source.name[-len("YYYYmmdd-HHMMSS") :]
        folder = store.experiments_dir / f"{target_id}-{started}"
        shutil.copytree(source, folder, dirs_exist_ok=True)
        for relative in _REPORT_ORDER:
            (folder / relative).touch()
    return target_id


def add_demo_target_to_new_local_user(store: Store) -> None:
    """Give the local user account the demo Target, when the store has no local user account yet.

    The store makes the local user account with its first Target. A store that has the account
    keeps its Targets as they are, so a demo that the user deleted stays deleted.
    """
    with store.engine.connect() as connection:
        known = connection.execute(
            select(users.c.id).where(users.c.id == LOCAL_USER_ID)
        ).first()
    if known is None:
        add_demo_target(store)


__all__ = [
    "DEMO_FILES",
    "EXPERIMENTS",
    "INTERVIEW",
    "RECORD",
    "add_demo_target",
    "add_demo_target_to_new_local_user",
]
