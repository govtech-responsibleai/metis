// Follows one Experiment while its run is alive, and starts its engine steps.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  experimentState,
  type ExperimentState,
  type ResumeStep,
} from "./experiment-status.ts";
import {
  api,
  store,
  TransportError,
  type EngineStatus,
  type ExperimentRecord,
  type ExperimentSave,
  type PhaseEvent,
} from "./transport/api.ts";

const POLL_MS = 2000;

export type WatchLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | {
      status: "ready";
      record: ExperimentRecord;
      state: ExperimentState;
      events: readonly PhaseEvent[];
    };

export interface StepCalls {
  engineStatus: (experimentId: string) => Promise<EngineStatus>;
  resumeSimulation: (experimentId: string) => Promise<void>;
  evaluate: (experimentId: string) => Promise<void>;
  resumeEvaluation: (experimentId: string) => Promise<void>;
  putExperiment: (
    experimentId: string,
    body: ExperimentSave,
  ) => Promise<ExperimentRecord>;
}

const STEP_CALLS: StepCalls = {
  engineStatus: api.engineStatus,
  resumeSimulation: api.resumeSimulation,
  evaluate: api.evaluate,
  resumeEvaluation: api.resumeEvaluation,
  putExperiment: store.putExperiment,
};

const RESUME: Record<
  ResumeStep,
  {
    start: (calls: StepCalls) => (experimentId: string) => Promise<void>;
    step: ExperimentRecord["step"];
    phase: EngineStatus["phase"];
  }
> = {
  "resume-simulate": {
    start: (calls) => calls.resumeSimulation,
    step: "simulate",
    phase: "simulating",
  },
  evaluate: {
    start: (calls) => calls.evaluate,
    step: "evaluate",
    phase: "evaluating",
  },
  "resume-evaluate": {
    start: (calls) => calls.resumeEvaluation,
    step: "evaluate",
    phase: "evaluating",
  },
};

export const STALE_STEP =
  "This Experiment changed since the page last read it, so nothing started. The page now shows its current state.";

function isLiveStatus(status: EngineStatus): boolean {
  return status.status === "running" || status.status === "stopping";
}

// Starts the engine step that a Resume was for, and saves the step of the row.
//
// The page acts on the state of its last poll, and polling stops when no run is alive. Another
// tab can change the Experiment since then, so the status is read again first. When the state
// now needs a different step, or none, nothing starts and the error is STALE_STEP.
//
// `run_in_progress` means that a run of this Experiment is alive. The step is saved only when
// that run is of the phase of the step, so the row never names a step that is not running.
export async function startStep(
  step: ResumeStep,
  record: ExperimentRecord,
  calls: StepCalls = STEP_CALLS,
): Promise<ExperimentRecord> {
  const id = record.experiment_id;
  const now = experimentState(record.step, await calls.engineStatus(id), []);
  if (!("resume" in now) || now.resume !== step) throw new Error(STALE_STEP);
  const { start, step: saved, phase } = RESUME[step];
  try {
    await start(calls)(id);
  } catch (cause) {
    if (!(cause instanceof TransportError && cause.code === "run_in_progress"))
      throw cause;
    const live = await calls.engineStatus(id);
    if (!isLiveStatus(live) || live.phase !== phase) return record;
  }
  if (record.step === saved) return record;
  return calls.putExperiment(id, { target_id: record.target_id, step: saved });
}

// The Experiments whose evaluate this page started on its own. It is outside the component, so
// a second mount in strict mode, or a second poll, cannot start evaluate again.
const autoStarted = new Set<string>();

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
  const [record, setRecord] = useState<ExperimentRecord | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"stop" | "resume" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // The Experiment whose simulate this page saw run.
  const sawSimulate = useRef<string | null>(null);
  const { engine, failure } = useEngine(experimentId, wake);

  useEffect(() => {
    let current = true;
    setRecord(null);
    setRecordError(null);
    store.experiment(experimentId).then(
      (found) => {
        if (current) setRecord(found);
      },
      (cause: unknown) => {
        if (current) setRecordError(errorText(cause));
      },
    );
    return () => {
      current = false;
    };
  }, [experimentId]);

  const state =
    record && engine
      ? experimentState(record.step, engine.status, engine.events)
      : null;

  // A refused or stale start shows its message, and `act` polls again to show the new state.
  const start = useCallback(
    async (step: ResumeStep, current: ExperimentRecord) => {
      setRecord(await startStep(step, current));
    },
    [],
  );

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

  // Evaluate starts when this page sees simulate end. When no page is open at that moment, the
  // Experiment waits for evaluate, and Resume starts it.
  useEffect(() => {
    if (state?.kind === "simulating") {
      sawSimulate.current = experimentId;
      // A resumed simulation ends again, and its evaluate starts again.
      autoStarted.delete(experimentId);
    }
    if (
      state?.kind !== "waiting" ||
      !record ||
      sawSimulate.current !== experimentId ||
      autoStarted.has(experimentId)
    )
      return;
    autoStarted.add(experimentId);
    act("resume", () => start("evaluate", record));
  }, [state?.kind, record, experimentId, act, start]);

  const load: WatchLoad =
    recordError !== null
      ? { status: "failed", message: recordError }
      : failure !== null
        ? { status: "failed", message: failure }
        : record && engine && state
          ? { status: "ready", record, state, events: engine.events }
          : { status: "loading" };

  return {
    load,
    busy,
    actionError,
    stop: () => act("stop", () => api.stop(experimentId)),
    resume: () => {
      if (record && state && "resume" in state) {
        const step = state.resume;
        act("resume", () => start(step, record));
      }
    },
  };
}
