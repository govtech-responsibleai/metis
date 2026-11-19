"""The demo Target that a new user account gets."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from metis.api.demo import DEMO_FILES, EXPERIMENTS, add_demo_target_to_new_local_user
from metis.api.main import create_app
from metis.api.store import Store

ADMIN = {"Authorization": "Bearer workshop-admin-token"}
TARGETS = "/api/v1/targets"
NAME = "Northstar Policy & Report Assistant"
EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "packages/engine/examples/http-agentic_eval_toyapp-workshop-lite/specification"
)

MakeClient = Callable[..., TestClient]


@pytest.fixture
def login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METIS_LOGIN", "1")
    monkeypatch.setenv("METIS_ADMIN_TOKEN", "workshop-admin-token")
    monkeypatch.delenv("HOST", raising=False)


def _log_in(client: TestClient, user: dict[str, str]) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": user["username"], "password": user["password"]},
    )
    assert login.status_code == 200


@pytest.fixture
def new_user_browser(
    login_on: None, make_client: MakeClient
) -> Iterator[Callable[[], TestClient]]:
    """Make a browser that has the login session of a new user account."""
    with ExitStack() as stack:

        def _make() -> TestClient:
            client = stack.enter_context(make_client())
            client.user = client.post("/api/v1/users", headers=ADMIN).json()
            _log_in(client, client.user)
            return client

        yield _make


def _targets(client: TestClient) -> list[dict[str, str]]:
    return client.get(TARGETS).json()["targets"]


def test_a_new_user_account_has_the_demo_target_with_a_done_interview(
    new_user_browser: Callable[[], TestClient],
) -> None:
    browser = new_user_browser()

    [target] = _targets(browser)
    interview = browser.get(f"{TARGETS}/{target['id']}/interview").json()

    assert target["title"] == NAME
    assert interview["stage"] == "done"
    assert interview["state"]["confirmed"] is True
    assert interview["state"]["pending"] is None
    assert interview["state"]["context"]["connection"]["binding"]["identity"] == {
        "name": NAME
    }


def test_the_demo_specification_is_ready_for_a_new_experiment(
    new_user_browser: Callable[[], TestClient], store: Store
) -> None:
    browser = new_user_browser()
    [target] = _targets(browser)

    saved = browser.get(f"{TARGETS}/{target['id']}/specification").json()

    input_dir = store.for_user(browser.user["id"]).project_dir / saved["input_dir"]
    specification = yaml.safe_load(saved["specification_yaml"])
    assert specification["target"]["name"] == NAME
    assert sorted(path.name for path in input_dir.rglob("*") if path.is_file()) == [
        "northstar-q2-service-review.md",
        "specification.yaml",
        "target-binding.yaml",
    ]


def test_the_demo_experiment_shows_its_trials_and_its_report_with_no_new_run(
    new_user_browser: Callable[[], TestClient],
) -> None:
    browser = new_user_browser()
    [target] = _targets(browser)

    listed = browser.get(f"{TARGETS}/{target['id']}/experiments").json()
    [experiment] = listed["experiments"]
    experiment_id = experiment["experiment_id"]
    status = browser.get(f"/api/v1/engine/{experiment_id}").json()
    events = browser.get(f"/api/v1/engine/{experiment_id}/events").json()
    report = browser.get(f"/api/v1/experiments/{experiment_id}/report").json()
    page = browser.get(f"/api/v1/experiments/{experiment_id}/report.html")

    assert status["status"] == "completed"
    assert status["phase"] == "evaluating"
    assert len(events) > 6
    assert report["target"] == NAME
    assert len(report["trials"]["items"]) == 6
    assert all(trial["conversation"] for trial in report["trials"]["items"])
    assert NAME in page.text


def test_a_deleted_demo_target_does_not_come_back_at_the_next_login(
    new_user_browser: Callable[[], TestClient],
) -> None:
    browser = new_user_browser()
    [target] = _targets(browser)

    assert browser.delete(f"{TARGETS}/{target['id']}").status_code == 204
    browser.post("/api/v1/auth/logout")
    _log_in(browser, browser.user)

    assert _targets(browser) == []


def test_each_user_account_has_its_own_copy_of_the_demo_target(
    new_user_browser: Callable[[], TestClient],
) -> None:
    first = new_user_browser()
    second = new_user_browser()
    [mine] = _targets(first)
    [theirs] = _targets(second)

    assert mine["id"] != theirs["id"]
    assert first.delete(f"{TARGETS}/{mine['id']}").status_code == 204

    assert _targets(first) == []
    assert _targets(second) == [theirs]
    assert first.get(f"{TARGETS}/{theirs['id']}/interview").status_code == 404


def test_an_app_that_builds_its_store_gives_the_local_user_the_demo_target_one_time(
    project_dir: Path,
) -> None:
    with TestClient(create_app(project_dir=project_dir)) as client:
        [target] = _targets(client)
        assert target["title"] == NAME
        assert client.delete(f"{TARGETS}/{target['id']}").status_code == 204

    with TestClient(create_app(project_dir=project_dir)) as client:
        assert _targets(client) == []


def test_a_store_with_a_local_user_account_gets_no_demo_target(store: Store) -> None:
    add_demo_target_to_new_local_user(store)
    [target] = store.list_targets().targets
    store.delete_target(target.id)

    add_demo_target_to_new_local_user(store)

    assert store.list_targets().targets == []


def test_the_demo_interview_has_the_specification_of_the_lite_example(
    store: Store,
) -> None:
    add_demo_target_to_new_local_user(store)
    [target] = store.list_targets().targets
    example = yaml.safe_load(
        (EXAMPLE / "specification.yaml").read_text(encoding="utf-8")
    )

    saved = yaml.safe_load(store.read_specification(target.id).specification_yaml)

    assert saved == {**example, "target_binding": "target-binding.yaml"}


def test_the_demo_files_are_only_the_files_that_the_web_app_reads() -> None:
    files = sorted(
        path.relative_to(DEMO_FILES).as_posix()
        for path in DEMO_FILES.rglob("*")
        if path.is_file()
    )
    [experiment] = [path.name for path in (DEMO_FILES / EXPERIMENTS).iterdir()]

    assert files == [
        f"evaluations/experiments/{experiment}/logs/events.jsonl",
        f"evaluations/experiments/{experiment}/outputs/reports/report.html",
        f"evaluations/experiments/{experiment}/outputs/reports/report.json",
        f"evaluations/experiments/{experiment}/outputs/reports/results.json",
        f"evaluations/experiments/{experiment}/specification/fixtures/northstar-q2-service-review.md",
        f"evaluations/experiments/{experiment}/specification/specification.yaml",
        f"evaluations/experiments/{experiment}/specification/toyapp-api.yaml",
        "evaluations/interviews/demo/documents/northstar-q2-service-review.md",
        "evaluations/interviews/demo/interview.json",
    ]


def test_the_demo_files_have_no_id_of_a_real_session() -> None:
    made_up = re.compile(r"00000000-0000-4000-8000-\d{12}")
    any_id = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

    for path in DEMO_FILES.rglob("*"):
        if path.is_file():
            found = set(any_id.findall(path.read_text(encoding="utf-8")))
            assert all(made_up.fullmatch(value) for value in found), path.name
