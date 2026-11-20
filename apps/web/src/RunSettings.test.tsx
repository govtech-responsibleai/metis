import assert from "node:assert/strict";
import { test } from "node:test";
import {
  START_BLOCKED,
  completesNow,
  interviewReady,
  filledRunModels,
  withRunModel,
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

test("the fields start with the recorded models, else the models of the environment", () => {
  const statuses: ModelStatus[] = [
    { ...status("user_agent", true), model: "env-ua" },
    { ...status("runner_agent", true), model: "env-ra" },
    { ...status("judge", true), model: "env-judge" },
  ];
  assert.deepEqual(filledRunModels(specification, statuses), {
    user_agent: "env-ua",
    judge: "env-judge",
  });
  const bound = {
    ...specification,
    target_binding: {},
    defaults: { judge_model: "spec-judge" },
  } as unknown as Specification;
  assert.deepEqual(filledRunModels(bound, statuses), {
    user_agent: "env-ua",
    runner_agent: "env-ra",
    judge: "spec-judge",
  });
});

test("the runner agent field follows the user agent field until the user changes it, as the engine does", () => {
  const statuses: ModelStatus[] = [
    { ...status("user_agent", true), model: "env-ua" },
    {
      ...status("runner_agent", true),
      model: "env-ua",
      source: "user agent model",
    },
  ];
  const bound = {
    ...specification,
    target_binding: {},
  } as unknown as Specification;
  const filled = filledRunModels(bound, statuses);
  assert.equal(filled.runner_agent, "env-ua");

  const typed = withRunModel(filled, "user_agent", "typed-ua", statuses);
  assert.equal(typed.runner_agent, "typed-ua");

  const own = withRunModel(typed, "runner_agent", "own-ra", statuses);
  assert.equal(
    withRunModel(own, "user_agent", "other-ua", statuses).runner_agent,
    "own-ra",
  );

  const ownModel: ModelStatus[] = [
    statuses[0],
    { ...status("runner_agent", true), model: "env-ra" },
  ];
  const separate = filledRunModels(bound, ownModel);
  assert.equal(
    withRunModel(separate, "user_agent", "typed-ua", ownModel).runner_agent,
    "env-ra",
  );
});

test("the run settings step opens on every path that completes the Interview", () => {
  const inProgress = { id: "a", done: false };
  const done = { id: "a", done: true };
  assert.equal(completesNow(inProgress, done), true);
  assert.equal(completesNow(null, done), false);
  assert.equal(completesNow({ id: "b", done: false }, done), false);
  assert.equal(completesNow(done, done), false);
  assert.equal(completesNow(done, inProgress), false);
});
