import assert from "node:assert/strict";
import { test } from "node:test";
import { STALE_STEP, startStep, type StepCalls } from "./experiment-watch.ts";
import {
  TransportError,
  type EngineStatus,
  type ExperimentRecord,
} from "./transport/api.ts";

const RECORD: ExperimentRecord = {
  experiment_id: "e1",
  target_id: "t1",
  started_at: "2026-01-02T03:04:05Z",
  step: "simulate",
};

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
    putExperiment: async (experimentId, body) => {
      calls.push(`save ${experimentId} ${body.step}`);
      return { ...RECORD, ...body, experiment_id: experimentId };
    },
  };
  return { calls, fake };
}

test("a Resume reads the status again, then starts its step and saves it", async () => {
  const { calls, fake } = recording([status({})]);

  const saved = await startStep("evaluate", RECORD, fake);

  assert.deepEqual(calls, ["status e1", "evaluate e1", "save e1 evaluate"]);
  assert.equal(saved.step, "evaluate");
});

test("a stale page that waits for evaluate starts nothing when the evaluate completed elsewhere", async () => {
  // Tab 1 shows "Waiting for evaluate". Tab 2 started the evaluate, and it completed.
  const { calls, fake } = recording([
    status({ phase: "evaluating", status: "completed" }),
  ]);

  await assert.rejects(startStep("evaluate", RECORD, fake), {
    message: STALE_STEP,
  });
  assert.deepEqual(calls, ["status e1"]);
});

test("a stale page starts nothing while a run of the Experiment is alive", async () => {
  const { calls, fake } = recording([
    status({ phase: "evaluating", status: "running" }),
  ]);

  await assert.rejects(
    startStep("resume-simulate", { ...RECORD, step: "simulate" }, fake),
    { message: STALE_STEP },
  );
  assert.deepEqual(calls, ["status e1"]);
});

test("a stale page starts nothing when the state needs a different step", async () => {
  // The page was for a full evaluate, but an evaluate since then stopped part way.
  const { calls, fake } = recording([
    status({ phase: "evaluating", status: "interrupted" }),
  ]);

  await assert.rejects(startStep("evaluate", RECORD, fake), {
    message: STALE_STEP,
  });
  assert.deepEqual(calls, ["status e1"]);
});

test("run_in_progress of the same phase saves the step", async () => {
  const { calls, fake } = recording(
    [status({}), status({ phase: "evaluating", status: "running" })],
    async () => {
      throw RUN_IN_PROGRESS;
    },
  );

  const saved = await startStep("evaluate", RECORD, fake);

  assert.deepEqual(calls, [
    "status e1",
    "evaluate e1",
    "status e1",
    "save e1 evaluate",
  ]);
  assert.equal(saved.step, "evaluate");
});

test("run_in_progress of a different phase keeps the saved step", async () => {
  // A resume-simulate click while an evaluate runs must not save the step `simulate`.
  const record: ExperimentRecord = { ...RECORD, step: "evaluate" };
  const { calls, fake } = recording(
    [
      status({ phase: "simulating", status: "interrupted" }),
      status({ phase: "evaluating", status: "running" }),
    ],
    async () => {
      throw RUN_IN_PROGRESS;
    },
  );

  const saved = await startStep("resume-simulate", record, fake);

  assert.deepEqual(calls, ["status e1", "resume-simulate e1", "status e1"]);
  assert.equal(saved, record);
});

test("a start that the API refuses saves no step", async () => {
  const complete = new TransportError("The evaluation is complete.", {
    status: 409,
    code: "evaluation_complete",
    retryable: false,
  });
  const { calls, fake } = recording([status({})], async () => {
    throw complete;
  });

  await assert.rejects(startStep("evaluate", RECORD, fake), complete);
  assert.deepEqual(calls, ["status e1", "evaluate e1"]);
});

test("a Resume of a queued Experiment starts nothing", async () => {
  const { calls, fake } = recording([
    status({ status: "queued", queue_ahead: 2 }),
  ]);

  await assert.rejects(
    startStep("resume-simulate", { ...RECORD, step: "simulate" }, fake),
    { message: STALE_STEP },
  );
  assert.deepEqual(calls, ["status e1"]);
});

test("run_in_progress of a queued job of the same phase saves the step", async () => {
  // The start was accepted by another tab and waits in the queue on the server.
  const record: ExperimentRecord = { ...RECORD, step: "simulate" };
  const { calls, fake } = recording(
    [
      status({ phase: "evaluating", status: "interrupted" }),
      status({ phase: "evaluating", status: "queued", queue_ahead: 0 }),
    ],
    async () => {
      throw RUN_IN_PROGRESS;
    },
  );

  const saved = await startStep("resume-evaluate", record, fake);

  assert.deepEqual(calls, [
    "status e1",
    "resume-evaluate e1",
    "status e1",
    "save e1 evaluate",
  ]);
  assert.equal(saved.step, "evaluate");
});
