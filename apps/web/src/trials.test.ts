import assert from "node:assert/strict";
import { test } from "node:test";
import { statusCounts, trialPlan, trialRows } from "./trials.ts";
import type { PhaseEvent, Specification } from "./transport/api.ts";

const specification = {
  personas: [
    { id: "p1", name: "New customer", description: "" },
    { id: "p2", name: "Old customer", description: "" },
  ],
  scenarios: [
    { id: "s1", name: "Opens an account", description: "" },
    { id: "s2", name: "Closes an account", description: "" },
  ],
  tasks: [
    { id: "t1", scenario_ref: "s1", persona_ref: "p1", num_trials: 2 },
    { id: "t2", scenario_ref: "s2", persona_ref: "p2", num_trials: 10 },
  ],
} as unknown as Specification;

const plan = trialPlan(specification);

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

const statusOf = (events: PhaseEvent[], live = true): Record<string, string> =>
  Object.fromEntries(
    trialRows(plan, events, live).map((row) => [row.trial, row.status]),
  );

test("the plan names each trial folder as the engine does, with its Persona and Scenario", () => {
  assert.equal(plan.length, 12);
  assert.deepEqual(plan[0], {
    trial: "t1-p1-1",
    taskId: "t1",
    index: 1,
    persona: "New customer",
    scenario: "Opens an account",
  });
  assert.equal(plan[2]?.trial, "t2-p2-01");
  assert.equal(plan[11]?.trial, "t2-p2-10");
});

test("a trial with no event waits", () => {
  assert.deepEqual(
    new Set(Object.values(statusOf([event({ total: 12, done: 0 })]))),
    new Set(["waiting"]),
  );
});

test("simulate events move each trial and keep the plan order", () => {
  const rows = trialRows(
    plan,
    [
      event({ total: 12, done: 0 }),
      event({ trial: "t2-p2-03", status: "started", attempt: 1 }),
      event({ trial: "t1-p1-2", status: "started", attempt: 1 }),
      event({ trial: "t1-p1-2", status: "running", attempt: 1, turn: 1 }),
      event({ trial: "t2-p2-03", status: "completed", attempt: 1 }),
      event({
        trial: "t1-p1-1",
        status: "failed",
        attempt: 3,
        reason: "Target returned HTTP 502",
      }),
    ],
    true,
  );

  assert.deepEqual(
    rows.slice(0, 5).map((row) => [row.trial, row.status, row.reason]),
    [
      ["t1-p1-1", "failed", "Target returned HTTP 502"],
      ["t1-p1-2", "simulating", null],
      ["t2-p2-01", "waiting", null],
      ["t2-p2-02", "waiting", null],
      ["t2-p2-03", "simulated", null],
    ],
  );
});

test("a retry clears the reason until the trial ends", () => {
  const [row] = trialRows(
    plan,
    [
      event({ trial: "t1-p1-1", status: "started", attempt: 1 }),
      event({
        trial: "t1-p1-1",
        status: "retrying",
        attempt: 1,
        reason: "timeout",
      }),
    ],
    true,
  );
  assert.equal(row?.status, "simulating");
  assert.equal(row?.reason, null);
});

test("a stop marks the trials in flight as stopped, with no reason", () => {
  const events = [
    event({ total: 12, done: 0 }),
    event({ trial: "t1-p1-1", status: "completed", attempt: 1 }),
    event({ trial: "t1-p1-2", status: "running", attempt: 1, turn: 2 }),
    event({ status: "interrupted", reason: "Stopped by Ctrl-C" }),
  ];
  const rows = trialRows(plan, events, false);

  assert.equal(rows[0]?.status, "simulated");
  assert.equal(rows[1]?.status, "stopped");
  assert.equal(rows[1]?.reason, null);
  assert.equal(rows[2]?.status, "waiting");
});

test("a run that ended with no line leaves no trial in flight", () => {
  const events = [
    event({ trial: "t1-p1-1", status: "running", attempt: 1, turn: 1 }),
  ];
  assert.equal(statusOf(events, true)["t1-p1-1"], "simulating");
  assert.equal(statusOf(events, false)["t1-p1-1"], "stopped");
});

test("evaluate grades the simulated trials, and a trial with no grade shows why", () => {
  const rows = trialRows(
    plan,
    [
      event({ trial: "t1-p1-1", status: "completed", attempt: 1 }),
      event({ trial: "t1-p1-2", status: "completed", attempt: 1 }),
      event({ status: "completed" }),
      event({ phase: "evaluating", total: 12, done: 0 }),
      event({ phase: "evaluating", trial: "t1-p1-1", status: "started" }),
      event({ phase: "evaluating", trial: "t1-p1-1", status: "completed" }),
      event({ phase: "evaluating", trial: "t1-p1-2", status: "started" }),
      event({
        phase: "evaluating",
        trial: "t1-p1-2",
        status: "failed",
        reason: "No traces",
      }),
    ],
    true,
  );

  assert.deepEqual(
    rows.slice(0, 2).map((row) => [row.status, row.reason]),
    [
      ["graded", null],
      ["grading-failed", "No traces"],
    ],
  );
});

test("a new simulate or evaluate clears the earlier grades, and a resume of evaluate keeps them", () => {
  const graded = [
    event({ trial: "t1-p1-1", status: "completed", attempt: 1 }),
    event({ phase: "evaluating", total: 12, done: 0 }),
    event({ phase: "evaluating", trial: "t1-p1-1", status: "completed" }),
    event({ phase: "evaluating", status: "completed" }),
  ];
  assert.equal(
    statusOf([...graded, event({ total: 12, done: 1 })])["t1-p1-1"],
    "simulated",
  );
  assert.equal(
    statusOf([...graded, event({ phase: "evaluating", total: 12, done: 0 })])[
      "t1-p1-1"
    ],
    "simulated",
  );
  assert.equal(
    statusOf([...graded, event({ phase: "evaluating", total: 12, done: 1 })])[
      "t1-p1-1"
    ],
    "graded",
  );
});

test("a trial that the plan does not name gets its own row at the end", () => {
  const rows = trialRows(
    plan,
    [event({ trial: "old-p9-1", status: "completed", attempt: 1 })],
    true,
  );
  assert.deepEqual(rows.at(-1), {
    trial: "old-p9-1",
    taskId: null,
    index: null,
    persona: null,
    scenario: null,
    status: "simulated",
    reason: null,
  });
});

test("the counts add up the rows of each status", () => {
  const counts = statusCounts(
    trialRows(
      plan,
      [event({ trial: "t1-p1-1", status: "completed", attempt: 1 })],
      true,
    ),
  );
  assert.equal(counts.simulated, 1);
  assert.equal(counts.waiting, 11);
  assert.equal(counts.failed, 0);
});

test("a trial that did not run keeps its reason through evaluate", () => {
  const [row] = trialRows(
    plan,
    [
      event({
        trial: "t1-p1-1",
        status: "failed",
        attempt: 1,
        reason: "fixture_never_uploaded: policy.pdf",
      }),
      event({ status: "completed" }),
      event({ phase: "evaluating", total: 12, done: 0 }),
      event({ phase: "evaluating", trial: "t1-p1-1", status: "started" }),
      event({
        phase: "evaluating",
        trial: "t1-p1-1",
        status: "failed",
        reason: "No target_session_id",
      }),
    ],
    false,
  );
  assert.deepEqual(
    [row?.status, row?.reason],
    ["failed", "fixture_never_uploaded: policy.pdf"],
  );
});
