import assert from "node:assert/strict";
import { test } from "node:test";
import {
  START_BLOCKED,
  interviewReady,
  placeholderModel,
  stateForDownload,
  withRunModels,
} from "./RunSettings";
import type {
  InterviewState,
  ModelStatus,
  Specification,
} from "./transport/api";

function status(
  role: ModelStatus["role"],
  configured: boolean,
  missing_vars: string[] = [],
): ModelStatus {
  return {
    role,
    label: role,
    model: `${role}-model`,
    source: `${role.toUpperCase()}_MODEL`,
    configured,
    affects_scores: role !== "interview",
    missing_vars,
  };
}

const specification: Specification = {
  schema_version: 1,
  id: "test",
  runner_factory_ref: "metis.engine.simulation.runners.http.HttpRunnerFactory",
  target: { name: "T", users: "U", description: "D", detail: "" },
  features: [],
  personas: [],
  scenarios: [],
  tasks: [],
};

const state = {
  specification,
  behaviours_confirmed: true,
  confirmed: true,
  history: [],
  user_typed: [],
  issued_ids: [],
  pending: null,
} as unknown as InterviewState;

test("only the Interview key blocks the start", () => {
  const noInterview = [
    status("interview", false, ["INTERVIEW_API_KEY", "OPENAI_API_KEY"]),
  ];
  assert.equal(interviewReady(noInterview), false);
  assert.equal(START_BLOCKED, "Configure API keys to start interview");

  const noRunKeys = [
    status("interview", true),
    status("user_agent", false),
    status("judge", false),
  ];
  assert.equal(interviewReady(noRunKeys), true);
});

test("the run settings step writes model names only into the experiment defaults", () => {
  const next = withRunModels(state, {
    user_agent: " ua-model ",
    judge: "judge-model",
  });
  assert.deepEqual(next.specification.defaults, {
    user_agent_model: "ua-model",
    judge_model: "judge-model",
  });
  assert.deepEqual(
    { ...next.specification, defaults: undefined },
    { ...specification, defaults: undefined },
  );
  assert.deepEqual(withRunModels(next, { judge: "" }).specification.defaults, {
    user_agent_model: "ua-model",
  });
});

test("continuing with no change packages the same state as before the step", () => {
  assert.equal(stateForDownload(state, null), state);
  assert.deepEqual(
    stateForDownload(state, { judge: "j" }).specification.defaults,
    { judge_model: "j" },
  );
});

test("the runner agent placeholder follows the user agent model, as the engine does", () => {
  const statuses: ModelStatus[] = [
    { ...status("user_agent", true), model: "env-ua" },
    {
      ...status("runner_agent", true),
      model: "env-ua",
      source: "user agent model",
    },
  ];
  assert.equal(placeholderModel("runner_agent", statuses, {}), "env-ua");
  assert.equal(
    placeholderModel("runner_agent", statuses, { user_agent: " typed-ua " }),
    "typed-ua",
  );
  const ownModel: ModelStatus[] = [
    statuses[0],
    { ...status("runner_agent", true), model: "env-ra" },
  ];
  assert.equal(
    placeholderModel("runner_agent", ownModel, { user_agent: "typed-ua" }),
    "env-ra",
  );
  assert.equal(
    placeholderModel("user_agent", statuses, { user_agent: "typed-ua" }),
    "env-ua",
  );
});
