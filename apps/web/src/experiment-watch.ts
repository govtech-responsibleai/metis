// Follows one Experiment while its run is alive or queued, and starts the steps that the user
// asks for. The server starts the evaluate after a simulate, so this page never starts one on
// its own.

import { useCallback, useEffect, useState } from "react";
import {
  experimentState,
  type ExperimentState,
  type ResumeStep,
} from "./experiment-status.ts";
import {
  api,
  TransportError,
  type EngineStatus,
  type PhaseEvent,
} from "./transport/api.ts";

const POLL_MS = 2000;

export type WatchLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | {
      status: "ready";
      state: ExperimentState;
      events: readonly PhaseEvent[];
    };

export interface StepCalls {
  engineStatus: (experimentId: string) => Promise<EngineStatus>;
  resumeSimulation: (experimentId: string) => Promise<void>;
  evaluate: (experimentId: string) => Promise<void>;
  resumeEvaluation: (experimentId: string) => Promise<void>;
}

const STEP_CALLS: StepCalls = {
  engineStatus: api.engineStatus,
  resumeSimulation: api.resumeSimulation,
  evaluate: api.evaluate,
  resumeEvaluation: api.resumeEvaluation,
};

const RESUME: Record<
  ResumeStep,
  (calls: StepCalls) => (experimentId: string) => Promise<void>
> = {
  "resume-simulate": (calls) => calls.resumeSimulation,
  evaluate: (calls) => calls.evaluate,
  "resume-evaluate": (calls) => calls.resumeEvaluation,
};

export const STALE_STEP =
  "This Experiment changed since the page last read it, so nothing started. The page now shows its current state.";

// A queued run is alive too: it waits on the server for a free slot, and starts on its own.
function isLiveStatus(status: EngineStatus): boolean {
  return (
    status.status === "running" ||
    status.status === "stopping" ||
    status.status === "queued"
  );
}

// Starts the engine step that a Resume was for.
//
// The page acts on the state of its last poll, and polling stops when no run is alive. Another
// tab can change the Experiment since then, so the status is read again first. When the state
// now needs a different step, or none, nothing starts and the error is STALE_STEP.
//
// `run_in_progress` means that a run of this Experiment is alive already, so it is not an error:
// the next poll shows that run.
export async function startStep(
  step: ResumeStep,
  experimentId: string,
  calls: StepCalls = STEP_CALLS,
): Promise<void> {
  const now = experimentState(await calls.engineStatus(experimentId), []);
  if (!("resume" in now) || now.resume !== step) throw new Error(STALE_STEP);
  try {
    await RESUME[step](calls)(experimentId);
  } catch (cause) {
    if (!(cause instanceof TransportError && cause.code === "run_in_progress"))
      throw cause;
  }
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

interface Engine {
  experimentId: string;
  status: EngineStatus;
  events: PhaseEvent[];
}

// Each visit reads the events from seq 0, so a reload rebuilds the same rows. Then it reads only
// the new events, every two seconds while the run is alive. A hidden tab waits. A new `wake`
// starts to poll again, for a run that an action started, and keeps the rows on the screen.
function useEngine(experimentId: string, wake: number) {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [failure, setFailure] = useState<{
    experimentId: string;
    message: string;
  } | null>(null);
  useEffect(() => {
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let events: PhaseEvent[] = [];
    const poll = async () => {
      let live = true;
      if (!document.hidden)
        try {
          // The status first, so the events are never older than the status.
          const status = await api.engineStatus(experimentId);
          const fresh = await api.engineEvents(
            experimentId,
            events.at(-1)?.seq ?? 0,
          );
          if (!current) return;
          events = [...events, ...fresh];
          setEngine({ experimentId, status, events });
          setFailure(null);
          live = isLiveStatus(status);
        } catch (cause) {
          if (!current) return;
          setFailure({ experimentId, message: errorText(cause) });
        }
      if (current && live) timer = setTimeout(() => void poll(), POLL_MS);
    };
    void poll();
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [experimentId, wake]);
  const shown = engine?.experimentId === experimentId ? engine : null;
  return {
    engine: shown,
    // A failed poll shows only when there are no rows to show.
    failure:
      shown === null && failure?.experimentId === experimentId
        ? failure.message
        : null,
  };
}

export function useExperimentWatch(experimentId: string): {
  load: WatchLoad;
  // An engine action that is running now, or null.
  busy: "stop" | "resume" | null;
  // The message of the last action that the API refused.
  actionError: string | null;
  stop: () => void;
  resume: () => void;
} {
  const [wake, setWake] = useState(0);
  const [busy, setBusy] = useState<"stop" | "resume" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { engine, failure } = useEngine(experimentId, wake);

  const state = engine ? experimentState(engine.status, engine.events) : null;

  // A refused or stale start shows its message, and the new `wake` polls again to show the new
  // state.
  const act = useCallback(
    (action: "stop" | "resume", work: () => Promise<void>) => {
      setBusy(action);
      setActionError(null);
      work().then(
        () => {
          setBusy(null);
          setWake((count) => count + 1);
        },
        (cause: unknown) => {
          setBusy(null);
          setActionError(errorText(cause));
          setWake((count) => count + 1);
        },
      );
    },
    [],
  );

  const load: WatchLoad =
    failure !== null
      ? { status: "failed", message: failure }
      : engine && state
        ? { status: "ready", state, events: engine.events }
        : { status: "loading" };

  return {
    load,
    busy,
    actionError,
    stop: () => act("stop", () => api.stop(experimentId)),
    resume: () => {
      if (state && "resume" in state) {
        const step = state.resume;
        act("resume", () => startStep(step, experimentId));
      }
    },
  };
}
