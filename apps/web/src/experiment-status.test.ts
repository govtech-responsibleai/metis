import assert from "node:assert/strict";
import { test } from "node:test";
import {
  experimentState,
  progressText,
  STATE_LABEL,
} from "./experiment-status.ts";
import type {
  EngineStatus,
  ExperimentRecord,
  PhaseEvent,
} from "./transport/api.ts";

const status = (fields: Partial<EngineStatus>): EngineStatus => ({
  experiment_id: "e1",
  phase: "simulating",
  status: "running",
  total: 4,
  done: 0,
  reason: null,
  last_seq: 0,
  ...fields,
});

let seq = 0;
const event = (fields: Partial<PhaseEvent>): PhaseEvent =>
  ({
    seq: (seq += 1),
    at: "2026-01-02T03:04:05Z",
    phase: "simulating",
    trial: null,
    status: "started",
    ...fields,
  }) as PhaseEvent;

const label = (
  fields: Partial<EngineStatus>,
  step: ExperimentRecord["step"] = "simulate",
) => STATE_LABEL[experimentState(step, status(fields), []).kind];

test("a live run shows its phase, also while it stops", () => {
  assert.equal(label({ phase: "simulating", status: "running" }), "Simulating");
  assert.equal(label({ phase: "evaluating", status: "running" }), "Evaluating");
  assert.equal(
    label({ phase: "evaluating", status: "stopping" }),
    "Evaluating",
  );
});

test("a completed simulation waits for evaluate", () => {
  assert.equal(label({ status: "completed" }), "Waiting for evaluate");
});

test("an Experiment is completed when evaluate completes", () => {
  assert.equal(
    label({ phase: "evaluating", status: "completed" }, "evaluate"),
    "Completed",
  );
});

test("a run that ended early is stopped and keeps its reason", () => {
  assert.deepEqual(
    experimentState(
      "evaluate",
      status({ phase: "evaluating", status: "failed", reason: "No traces" }),
      [],
    ),
    { kind: "stopped", progress: null, reason: "No traces" },
  );
  for (const ended of ["interrupted", "unfinished", "not_started"] as const)
    assert.equal(label({ status: ended }), "Stopped", ended);
});

test("progress counts each trial that ended in the newest phase", () => {
  const events = [
    event({ total: 4, done: 0 }),
    event({ trial: "t1", status: "completed", attempt: 1 }),
    event({ trial: "t2", status: "failed", attempt: 1 }),
    event({ status: "completed" }),
    event({ phase: "evaluating", total: 4, done: 1 }),
    event({ phase: "evaluating", trial: "t2", status: "started" }),
    event({ phase: "evaluating", trial: "t2", status: "completed" }),
  ];
  const state = experimentState(
    "evaluate",
    status({ phase: "evaluating" }),
    events,
  );

  assert.equal(progressText(state.progress), "2 of 4 graded");
});

test("a simulation shows its trials as simulated", () => {
  const events = [
    event({ total: 16, done: 4 }),
    event({ trial: "t1", status: "running", attempt: 1, turn: 2 }),
    event({ trial: "t1", status: "completed", attempt: 1 }),
  ];

  assert.equal(
    progressText(experimentState("simulate", status({}), events).progress),
    "5 of 16 simulated",
  );
});

test("an Experiment shows no progress before the engine counts its trials", () => {
  assert.equal(
    progressText(experimentState("simulate", status({}), []).progress),
    null,
  );
});
