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

// What the app shows for an Experiment.
export type ExperimentState =
  | { kind: "simulating" | "evaluating"; progress: Progress | null }
  // Simulate is done and evaluate has not started.
  | { kind: "waiting"; progress: Progress | null }
  | { kind: "completed"; progress: Progress | null }
  | { kind: "stopped"; progress: Progress | null; reason: string | null };

export const STATE_LABEL: Record<ExperimentState["kind"], string> = {
  simulating: "Simulating",
  evaluating: "Evaluating",
  waiting: "Waiting for evaluate",
  completed: "Completed",
  stopped: "Stopped",
};

export function isLive(state: ExperimentState): boolean {
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
    case "running":
    case "stopping":
      return { kind: phase, progress };
    case "completed":
      if (phase === "evaluating") return { kind: "completed", progress };
      // With the step `evaluate`, the app started evaluate and it wrote no line.
      return step === "simulate"
        ? { kind: "waiting", progress }
        : { kind: "stopped", progress, reason: null };
    case "failed":
    case "interrupted":
    case "unfinished":
    case "not_started":
      return { kind: "stopped", progress, reason: status.reason };
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
