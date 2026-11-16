// The trial table of an Experiment. The rows come from the Specification in the order that the
// engine plans its trials, and each event of the engine moves one row to its next status.

import type { PhaseEvent, Specification } from "./transport/api.ts";

export const TRIAL_STATUSES = [
  "waiting",
  "simulating",
  "simulated",
  "grading",
  "graded",
  "failed",
  "grading-failed",
  "stopped",
] as const;

export type TrialStatus = (typeof TRIAL_STATUSES)[number];

export const TRIAL_STATUS_LABEL: Record<TrialStatus, string> = {
  waiting: "Waiting",
  simulating: "Simulating",
  simulated: "Simulated",
  grading: "Grading",
  graded: "Graded",
  failed: "Failed",
  "grading-failed": "Not graded",
  stopped: "Stopped",
};

export interface PlannedTrial {
  // The name of the trial folder, `<task id>-<persona id>-<index>`. The events use it.
  trial: string;
  // Null for a trial that the Specification does not name.
  taskId: string | null;
  // The number of the trial in its Test Case, from 1. Null for a trial that the Specification
  // does not name.
  index: number | null;
  persona: string | null;
  scenario: string | null;
}

export interface TrialRow extends PlannedTrial {
  status: TrialStatus;
  // Why the trial did not run, or why evaluate could not grade it. Null for every other status.
  reason: string | null;
}

// Each Task runs its Persona in its Scenario `num_trials` times. This mirrors
// `expand_trial_plan` and `trial_folder_name` in metis.engine.simulation.experiment.
export function trialPlan(specification: Specification): PlannedTrial[] {
  const personas = new Map(specification.personas.map((p) => [p.id, p.name]));
  const scenarios = new Map(specification.scenarios.map((s) => [s.id, s.name]));
  return specification.tasks.flatMap((task) => {
    const pad = String(task.num_trials).length;
    return Array.from({ length: task.num_trials }, (_, offset) => ({
      trial: `${task.id}-${task.persona_ref}-${String(offset + 1).padStart(pad, "0")}`,
      taskId: task.id,
      index: offset + 1,
      persona: personas.get(task.persona_ref) ?? task.persona_ref,
      scenario: scenarios.get(task.scenario_ref) ?? task.scenario_ref,
    }));
  });
}

// The status that a trial line gives its row, by phase and by the status of the line.
const TRIAL_LINE: {
  [P in PhaseEvent["phase"]]: Partial<
    Record<PhaseEvent["status"], TrialStatus>
  >;
} = {
  simulating: {
    started: "simulating",
    running: "simulating",
    retrying: "simulating",
    completed: "simulated",
    failed: "failed",
    interrupted: "stopped",
  },
  evaluating: {
    started: "grading",
    completed: "graded",
    failed: "grading-failed",
  },
};

const HAS_EVALUATION: ReadonlySet<TrialStatus> = new Set([
  "grading",
  "graded",
  "grading-failed",
]);

const HAS_REASON: ReadonlySet<TrialStatus> = new Set([
  "failed",
  "grading-failed",
]);

const settled = (row: TrialRow, status: TrialStatus): TrialRow => ({
  ...row,
  status,
  reason: null,
});

// A trial that was in flight when its run ended writes no line of its own.
function ended(row: TrialRow): TrialRow {
  if (row.status === "simulating") return settled(row, "stopped");
  if (row.status === "grading") return settled(row, "simulated");
  return row;
}

function unplanned(trial: string): TrialRow {
  return {
    trial,
    taskId: null,
    index: null,
    persona: null,
    scenario: null,
    status: "waiting",
    reason: null,
  };
}

export function applyEvent(
  rows: ReadonlyMap<string, TrialRow>,
  event: PhaseEvent,
): Map<string, TrialRow> {
  const next = new Map(rows);
  if (event.trial === null) {
    // A simulation deletes the evaluation of the Experiment, and so does an evaluate that is
    // not a resume. A resume of evaluate counts the trials that it keeps in `done`.
    const clears =
      event.status === "started" &&
      (event.phase === "simulating" || !event.done);
    const stops = event.status === "failed" || event.status === "interrupted";
    for (const [trial, row] of next)
      if (clears && HAS_EVALUATION.has(row.status))
        next.set(trial, settled(row, "simulated"));
      else if (stops) next.set(trial, ended(row));
    return next;
  }
  const status = TRIAL_LINE[event.phase][event.status];
  if (status === undefined) return next;
  const row = next.get(event.trial) ?? unplanned(event.trial);
  // Evaluate also reads a trial that did not run. The row keeps why it did not run.
  if (row.status === "failed" && event.phase === "evaluating") return next;
  next.set(event.trial, {
    ...row,
    status,
    reason: HAS_REASON.has(status) ? (event.reason ?? null) : null,
  });
  return next;
}

// The rows of the plan in plan order, then each trial that the plan does not name, in the order
// of its first event. With `live` false, no trial is still in flight.
export function trialRows(
  plan: readonly PlannedTrial[],
  events: readonly PhaseEvent[],
  live: boolean,
): TrialRow[] {
  let rows = new Map<string, TrialRow>(
    plan.map((trial) => [
      trial.trial,
      { ...trial, status: "waiting", reason: null },
    ]),
  );
  for (const event of events) rows = applyEvent(rows, event);
  const list = [...rows.values()];
  return live ? list : list.map(ended);
}

export function statusCounts(
  rows: readonly TrialRow[],
): Record<TrialStatus, number> {
  const counts = Object.fromEntries(
    TRIAL_STATUSES.map((status) => [status, 0]),
  ) as Record<TrialStatus, number>;
  for (const row of rows) counts[row.status] += 1;
  return counts;
}
