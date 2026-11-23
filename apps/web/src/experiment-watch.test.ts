import assert from "node:assert/strict";
import { test } from "node:test";
import { STALE_STEP, startStep, type StepCalls } from "./experiment-watch.ts";
import { TransportError, type EngineStatus } from "./transport/api.ts";

const status = (fields: Partial<EngineStatus>): EngineStatus => ({
  experiment_id: "e1",
  phase: "simulating",
  status: "completed",
  total: 4,
  done: 0,
  reason: null,
  last_seq: 0,
  queue_ahead: null,
  ...fields,
});

const RUN_IN_PROGRESS = new TransportError("A run of e1 is alive.", {
  status: 409,
  code: "run_in_progress",
  retryable: false,
});

// Records each call. `statuses` gives the answer of each status read, in order.
function recording(
  statuses: EngineStatus[],
  start?: (name: string) => Promise<void>,
) {
  const calls: string[] = [];
  const begin = (name: string) => async (experimentId: string) => {
    calls.push(`${name} ${experimentId}`);
    await start?.(name);
  };
  const fake: StepCalls = {
    engineStatus: async (experimentId) => {
      calls.push(`status ${experimentId}`);
      const next = statuses.shift();
      assert.ok(next, "no status left");
      return next;
    },
    resumeSimulation: begin("resume-simulate"),
    evaluate: begin("evaluate"),
    resumeEvaluation: begin("resume-evaluate"),
  };
  return { calls, fake };
}

test("a Resume reads the status again, then starts its step", async () => {
  const { calls, fake } = recording([status({})]);

  await startStep("evaluate", "e1", fake);

  assert.deepEqual(calls, ["status e1", "evaluate e1"]);
});

test("a stale page that waits for evaluate starts nothing when the evaluate completed elsewhere", async () => {
  // Tab 1 shows "Waiting for evaluate". Tab 2 started the evaluate, and it completed.
  const { calls, fake } = recording([
    status({ phase: "evaluating", status: "completed" }),
  ]);

  await assert.rejects(startStep("evaluate", "e1", fake), {
    message: STALE_STEP,
  });
  assert.deepEqual(calls, ["status e1"]);
});

test("a stale page starts nothing while a run of the Experiment is alive", async () => {
  const { calls, fake } = recording([
    status({ phase: "evaluating", status: "running" }),
  ]);

  await assert.rejects(startStep("resume-simulate", "e1", fake), {
    message: STALE_STEP,
  });
  assert.deepEqual(calls, ["status e1"]);
});

test("a stale page starts nothing when the state needs a different step", async () => {
  // The page was for a full evaluate, but an evaluate since then stopped part way.
  const { calls, fake } = recording([
    status({ phase: "evaluating", status: "interrupted" }),
  ]);

  await assert.rejects(startStep("evaluate", "e1", fake), {
    message: STALE_STEP,
  });
  assert.deepEqual(calls, ["status e1"]);
});

test("a Resume is not an error when a run of the Experiment is alive already", async () => {
  // Another tab started a run between the status read and the start.
  const { calls, fake } = recording([status({})], async () => {
    throw RUN_IN_PROGRESS;
  });

  await startStep("evaluate", "e1", fake);

  assert.deepEqual(calls, ["status e1", "evaluate e1"]);
});

test("a Resume gives the error of a start that the API refuses", async () => {
  const complete = new TransportError("The evaluation is complete.", {
    status: 409,
    code: "evaluation_complete",
    retryable: false,
  });
  const { calls, fake } = recording([status({})], async () => {
    throw complete;
  });

  await assert.rejects(startStep("evaluate", "e1", fake), complete);
  assert.deepEqual(calls, ["status e1", "evaluate e1"]);
});

test("a Resume of a queued Experiment starts nothing", async () => {
  const { calls, fake } = recording([
    status({ status: "queued", queue_ahead: 2 }),
  ]);

  await assert.rejects(startStep("resume-simulate", "e1", fake), {
    message: STALE_STEP,
  });
  assert.deepEqual(calls, ["status e1"]);
});
