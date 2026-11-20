import assert from "node:assert/strict";
import { test } from "node:test";
import type {
  InterviewState,
  Task,
  TargetConnection,
} from "./transport/api.ts";
import { exportedSpecification } from "./export.ts";

const HTTP_RUNNER = "metis.engine.simulation.runners.http.HttpRunnerFactory";

function task(id: string, scenario: string): Task {
  return {
    id,
    scenario_ref: scenario,
    persona_ref: "p1",
    fixtures: [],
    num_trials: 1,
    behaviour_refs: [],
    max_turns: 10,
    timeout_minutes: 5,
    response_wait_ms: 0,
  };
}

function state(
  excluded: string[],
  connection: TargetConnection | null = null,
): InterviewState {
  return {
    specification: {
      schema_version: 1,
      id: "test",
      runner_factory_ref: HTTP_RUNNER,
      tasks: [task("t1", "s1"), task("t2", "s2"), task("t3", "s1")],
      target: { name: "Bot", users: "", description: "", detail: "" },
      features: [],
      personas: [],
      scenarios: [
        { id: "s1", name: "One", description: "" },
        { id: "s2", name: "Two", description: "" },
      ],
    },
    excluded_tasks: excluded,
    behaviours_confirmed: true,
    confirmed: true,
    context: {
      perspective: "end_user",
      opening_description: "",
      capability_evidence: null,
      connection,
    },
    history: [],
    user_typed: [],
    issued_ids: [],
    pending: null,
  };
}

const browserConnection = {
  transport: "browser",
  binding: {} as TargetConnection["binding"],
  status: "checked",
} as TargetConnection;

test("the export leaves out cleared Test Cases and the Scenarios that only they use", () => {
  const exported = exportedSpecification(state(["t2"]));

  assert.deepEqual(
    exported.tasks.map((item) => item.id),
    ["t1", "t3"],
  );
  assert.deepEqual(
    exported.scenarios.map((item) => item.id),
    ["s1"],
  );
});

test("an export with no connection keeps the runner and names no binding", () => {
  const exported = exportedSpecification(state([]));

  assert.equal(exported.runner_factory_ref, HTTP_RUNNER);
  assert.equal(exported.target_binding, undefined);
  assert.equal(exported.scenarios.length, 2);
});

test("a connected export names the runner of its transport and the binding file", () => {
  const exported = exportedSpecification(state([], browserConnection));

  assert.equal(
    exported.runner_factory_ref,
    "metis.engine.simulation.runners.browser.BrowserRunnerFactory",
  );
  assert.equal(exported.target_binding, "target-binding.yaml");
});
