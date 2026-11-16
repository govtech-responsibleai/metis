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

const RESUME: Record<
  ResumeStep,
  {
    start: (experimentId: string) => Promise<void>;
    step: ExperimentRecord["step"];
  }
> = {
  "resume-simulate": { start: api.resumeSimulation, step: "simulate" },
  evaluate: { start: api.evaluate, step: "evaluate" },
  "resume-evaluate": { start: api.resumeEvaluation, step: "evaluate" },
};

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
          live = status.status === "running" || status.status === "stopping";
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

  const start = useCallback(
    async (step: ResumeStep, current: ExperimentRecord) => {
      const { start: run, step: saved } = RESUME[step];
      try {
        await run(current.experiment_id);
      } catch (cause) {
        // The run of this Experiment is alive, so the step has already started.
        if (!(
          cause instanceof TransportError && cause.code === "run_in_progress"
        ))
          throw cause;
      }
      if (current.step !== saved)
        setRecord(
          await store.putExperiment(current.experiment_id, {
            target_id: current.target_id,
            step: saved,
          }),
        );
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
