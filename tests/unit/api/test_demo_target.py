"""The demo Target that a new user account gets."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from metis.api.demo import DEMO_FILES, EXPERIMENTS, add_demo_target_to_new_local_user
from metis.api.main import create_app
from metis.api.store import Store
from metis.core import execution_layout

ADMIN = {"Authorization": "Bearer workshop-admin-token"}
TARGETS = "/api/v1/targets"
APP = "Northstar Policy & Report Assistant"
NAME = f"(demo) {APP}"
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


def _example_with_the_demo_name() -> dict[str, Any]:
    example = yaml.safe_load(
        (EXAMPLE / "specification.yaml").read_text(encoding="utf-8")
    )
    return {**example, "target": {**example["target"], "name": NAME}}


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
    assert interview["state"]["specification"]["target"]["name"] == NAME
    assert interview["state"]["context"]["connection"]["binding"]["identity"] == {
        "name": APP
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

    trials = report["trials"]["items"]
    assert experiment_id.startswith("demo-toyapp-workshop-lite-")
    assert status["status"] == "completed"
    assert status["phase"] == "evaluating"
    assert status["total"] == 4
    assert {event["trial"] for event in events if event["trial"]} == {
        trial["id"] for trial in trials
    }
    assert report["target"] == NAME
    assert report["sessions"] == 4
    assert [(trial["task_id"], trial["trial_index"]) for trial in trials] == [
        ("TC-004", 1),
        ("TC-004", 2),
        ("TC-006", 1),
        ("TC-008", 1),
    ]
    assert all(trial["conversation"] for trial in trials)
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


def test_the_demo_interview_has_the_lite_example_with_the_demo_name(
    store: Store,
) -> None:
    add_demo_target_to_new_local_user(store)
    [target] = store.list_targets().targets

    saved = yaml.safe_load(store.read_specification(target.id).specification_yaml)

    assert saved == {
        **_example_with_the_demo_name(),
        "target_binding": "target-binding.yaml",
    }


def test_the_demo_experiment_ran_the_lite_example_with_the_demo_name() -> None:
    [experiment] = (DEMO_FILES / EXPERIMENTS).iterdir()

    frozen = experiment / execution_layout.SPECIFICATION

    assert (
        yaml.safe_load(frozen.read_text(encoding="utf-8"))
        == _example_with_the_demo_name()
    )


def test_the_demo_files_are_only_the_files_that_the_web_app_reads() -> None:
    files = sorted(
        path.relative_to(DEMO_FILES).as_posix()
        for path in DEMO_FILES.rglob("*")
        if path.is_file()
    )
    [experiment] = [path.name for path in (DEMO_FILES / EXPERIMENTS).iterdir()]

    traces = sorted(
        f"evaluations/experiments/{experiment}/outputs/traces/{path.name}"
        for path in (DEMO_FILES / EXPERIMENTS / experiment / "outputs/traces").iterdir()
    )

    assert len(traces) == 4
    assert files == [
        f"evaluations/experiments/{experiment}/logs/events.jsonl",
        f"evaluations/experiments/{experiment}/outputs/reports/report.html",
        f"evaluations/experiments/{experiment}/outputs/reports/report.json",
        f"evaluations/experiments/{experiment}/outputs/reports/results.json",
        *traces,
        f"evaluations/experiments/{experiment}/specification/fixtures/northstar-q2-service-review.md",
        f"evaluations/experiments/{experiment}/specification/specification.yaml",
        f"evaluations/experiments/{experiment}/specification/toyapp-api.yaml",
        "evaluations/interviews/demo/documents/northstar-q2-service-review.md",
        "evaluations/interviews/demo/interview.json",
    ]


def test_each_demo_trial_links_to_its_langfuse_session_and_has_its_traces(
    new_user_browser: Callable[[], TestClient],
) -> None:
    browser = new_user_browser()
    [target] = _targets(browser)
    [experiment] = browser.get(f"{TARGETS}/{target['id']}/experiments").json()[
        "experiments"
    ]
    experiment_id = experiment["experiment_id"]
    events = browser.get(f"/api/v1/engine/{experiment_id}/events").json()
    report = browser.get(f"/api/v1/experiments/{experiment_id}/report").json()
    [folder] = (DEMO_FILES / EXPERIMENTS).iterdir()

    ended = {
        event["trial"]: event["session_url"]
        for event in events
        if event["trial"]
        and event["phase"] == "simulating"
        and event["status"] == "completed"
    }
    for trial in report["trials"]["items"]:
        assert trial["sessionUrl"].endswith(f"/sessions/{trial['session']}")
        assert ended[trial["id"]] == trial["sessionUrl"]
        traces = folder / execution_layout.TRACES
        assert (traces / execution_layout.trace_file_name(trial["session"])).is_file()
