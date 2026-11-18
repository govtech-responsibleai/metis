import type {
  EngineStatus,
  ExperimentRecord,
  PhaseEvent,
} from "./transport/api.ts";

type Phase = PhaseEvent["phase"];

// The trials of the newest phase that have ended, of `total`. Null before the engine counts them.
export interface Progress {
  phase: Phase;
  ended: number;
  total: number;
}

// The engine step that Resume starts. `resume-simulate` runs the trials that did not end,
// `evaluate` grades every trial, and `resume-evaluate` grades the trials with no evaluation.
export type ResumeStep = "resume-simulate" | "evaluate" | "resume-evaluate";

// What the app shows for an Experiment.
export type ExperimentState =
  | {
      kind: "simulating" | "evaluating";
      progress: Progress | null;
      // True after a stop, until the run ends.
      stopping: boolean;
    }
  // The run waits on the server for a free slot. `phase` is the phase of its first step, and
  // `queueAhead` is the number of runs before it, so 0 means that it starts next.
  | {
      kind: "queued";
      phase: Phase;
      progress: Progress | null;
      queueAhead: number;
    }
  // Simulate is done and evaluate has not started, for example after an API restart.
  | { kind: "waiting"; progress: Progress | null; resume: "evaluate" }
  | { kind: "completed"; progress: Progress | null }
  | {
      kind: "stopped";
      progress: Progress | null;
      reason: string | null;
      resume: ResumeStep;
    };

export type ExperimentAction = "stop" | "resume" | "delete";

// The actions that are on in each state. Delete is off while a run is alive or queued.
export const ACTIONS: Record<
  ExperimentState["kind"],
  Record<ExperimentAction, boolean>
> = {
  simulating: { stop: true, resume: false, delete: false },
  evaluating: { stop: true, resume: false, delete: false },
  queued: { stop: true, resume: false, delete: false },
  waiting: { stop: false, resume: true, delete: true },
  completed: { stop: false, resume: false, delete: true },
  stopped: { stop: false, resume: true, delete: true },
};

export type StepPhase = "done" | "live" | "paused" | "next";

// The two steps of an Experiment, Simulate and Evaluate, and where each one is.
export function phaseSteps(state: ExperimentState): {
  simulate: StepPhase;
  evaluate: StepPhase;
} {
  switch (state.kind) {
    case "simulating":
      return { simulate: "live", evaluate: "next" };
    case "evaluating":
      return { simulate: "done", evaluate: "live" };
    case "queued":
      return state.phase === "evaluating"
        ? { simulate: "done", evaluate: "next" }
        : { simulate: "next", evaluate: "next" };
    case "waiting":
      return { simulate: "done", evaluate: "next" };
    case "completed":
      return { simulate: "done", evaluate: "done" };
    case "stopped":
      return state.resume === "resume-simulate"
        ? { simulate: "paused", evaluate: "next" }
        : {
            simulate: "done",
            evaluate: state.resume === "evaluate" ? "next" : "paused",
          };
  }
}

// The part of each step that is done, from 0 to 1. Only the step of the newest phase has a count.
export function stepParts(state: ExperimentState): {
  simulate: number;
  evaluate: number;
} {
  const steps = phaseSteps(state);
  const part = (step: StepPhase, phase: Phase) => {
    if (step === "done") return 1;
    const progress = state.progress;
    return progress?.phase === phase && progress.total > 0
      ? progress.ended / progress.total
      : 0;
  };
  return {
    simulate: part(steps.simulate, "simulating"),
    evaluate: part(steps.evaluate, "evaluating"),
  };
}

export const STATE_LABEL: Record<ExperimentState["kind"], string> = {
  simulating: "Simulating",
  evaluating: "Evaluating",
  queued: "Queued",
  waiting: "Waiting for evaluate",
  completed: "Completed",
  stopped: "Stopped",
};

// The place of a queued Experiment, shown next to its state.
export function queueText(queueAhead: number): string {
  return queueAhead === 0 ? "Starts next" : `${queueAhead} ahead`;
}

export type LiveState = Extract<ExperimentState, { stopping: boolean }>;

export function isLive(state: ExperimentState): state is LiveState {
  return state.kind === "simulating" || state.kind === "evaluating";
}

export function experimentState(
  step: ExperimentRecord["step"],
  status: EngineStatus,
  events: readonly PhaseEvent[],
): ExperimentState {
  const progress = progressOf(events);
  const phase = status.phase ?? "simulating";
  switch (status.status) {
    case "queued":
      return {
        kind: "queued",
        phase,
        progress: null,
        queueAhead: status.queue_ahead ?? 0,
      };
    case "running":
    case "stopping":
      return { kind: phase, progress, stopping: status.status === "stopping" };
    case "completed":
      // The server starts the evaluate after a simulate, so the step can be `simulate`.
      if (phase === "evaluating") return { kind: "completed", progress };
      // With the step `evaluate`, the app started evaluate and it wrote no line.
      return step === "simulate"
        ? { kind: "waiting", progress, resume: "evaluate" }
        : { kind: "stopped", progress, reason: null, resume: "evaluate" };
    case "failed":
    case "interrupted":
    case "unfinished":
    case "not_started":
      return {
        kind: "stopped",
        progress,
        reason: status.reason,
        resume: phase === "evaluating" ? "resume-evaluate" : "resume-simulate",
      };
  }
}

// A phase starts with a `started` line that counts its trials and the ones that an earlier run
// finished. Each trial that ends after it writes a `completed` or `failed` line.
export function progressOf(events: readonly PhaseEvent[]): Progress | null {
  let start = events.length - 1;
  while (
    start >= 0 &&
    !(events[start]?.trial === null && events[start]?.status === "started")
  )
    start -= 1;
  const started = events[start];
  if (started?.total == null) return null;
  const ended = new Set(
    events
      .slice(start + 1)
      .filter(
        (event) =>
          event.trial !== null &&
          event.phase === started.phase &&
          (event.status === "completed" || event.status === "failed"),
      )
      .map((event) => event.trial),
  );
  return {
    phase: started.phase,
    ended: Math.min(started.total, (started.done ?? 0) + ended.size),
    total: started.total,
  };
}

const PHASE_WORD: Record<Phase, string> = {
  simulating: "simulated",
  evaluating: "graded",
};

export function progressText(progress: Progress | null): string | null {
  if (progress === null) return null;
  return `${progress.ended} of ${progress.total} ${PHASE_WORD[progress.phase]}`;
}
