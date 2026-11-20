// The experiment pages. An experiment has its trials and its report, and the list of all
// experiments has the Experiments of every Target. The comparison says what it will show.

import {
  ChevronLeft,
  CircleAlert,
  RotateCcw,
  Square,
  Trash2,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation } from "wouter";
import { ACTIONS, isLive, type ExperimentState } from "./experiment-status";
import { useExperimentWatch, type WatchLoad } from "./experiment-watch";
import {
  arrivedAtReport,
  experimentScreen,
  loadReport,
  type ExperimentScreen,
  type ReportLoad,
  type SettledReportLoad,
} from "./report";
import {
  ExperimentList,
  useExperimentList,
  type ExperimentItem,
  type ListLoad,
} from "./ExperimentList";
import { DownloadReport, ReportTab } from "./ReportTab";
import { store, type Specification } from "./transport/api";
import { paths, type ExperimentPart, type ExperimentTab } from "./routes";
import { trialPlan, trialRows, type TrialRow } from "./trials";
import { TrialsTab } from "./TrialsTab";
import { Button, cn, ConfirmDialog } from "./ui";

function Page({ children }: { children: ReactNode }) {
  return (
    <div className="quiet-scrollbar min-h-0 flex-1 overflow-y-auto px-6 py-6">
      <div className="flex flex-col gap-6">{children}</div>
    </div>
  );
}

function BackLink({ targetId, title }: { targetId: string; title: string }) {
  return (
    <Link
      href={paths.target(targetId, "experiments")}
      className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ChevronLeft size={14} aria-hidden />
      {title}
    </Link>
  );
}

function Placeholder({ children }: { children: string }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

const TABS: Array<{ id: ExperimentTab; label: string }> = [
  { id: "trials", label: "Trials" },
  { id: "report", label: "Report" },
];

const TAB =
  "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-150";

const LOADING: ReportLoad = { status: "loading" };

// The state holds the experiment and the request of its answer. The answer of another
// experiment reads as loading. A reload of the same experiment keeps the earlier answer until
// the new one comes, so the screen does not go back to loading in between.
function useReportLoad(experimentId: string): {
  load: ReportLoad;
  reload: () => void;
} {
  const [attempt, setAttempt] = useState(0);
  const [held, setHeld] = useState<{
    experimentId: string;
    key: string;
    load: SettledReportLoad;
  } | null>(null);
  const key = `${attempt}:${experimentId}`;
  useEffect(() => {
    let current = true;
    void loadReport(experimentId).then((load) => {
      if (current) setHeld({ experimentId, key, load });
    });
    return () => {
      current = false;
    };
  }, [experimentId, key]);
  const reload = useCallback(() => setAttempt((count) => count + 1), []);
  return {
    load: held?.experimentId === experimentId ? held.load : LOADING,
    reload,
  };
}

interface ExperimentProps {
  targetId: string;
  targetTitle: string;
  experimentId: string;
}

type Busy = "stop" | "resume" | "delete" | null;

// The run of the Experiment, as the view draws it.
export type RunView =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | {
      status: "ready";
      state: ExperimentState;
      trials: TrialRow[];
      busy: Busy;
      // The message of the last action that the API refused.
      error: string | null;
    };

export interface RunActions {
  stop: () => void;
  resume: () => void;
  remove: () => void;
}

function runView(
  watch: WatchLoad,
  plan: ReturnType<typeof trialPlan>,
  busy: Busy,
  error: string | null,
): RunView {
  if (watch.status !== "ready") return watch;
  return {
    status: "ready",
    state: watch.state,
    trials: trialRows(plan, watch.events, isLive(watch.state)),
    busy,
    error,
  };
}

export function ExperimentPage({
  part,
  specification,
  ...experiment
}: ExperimentProps & {
  part: ExperimentPart;
  // The Specification of the Target. It gives the names of the trials.
  specification: Specification;
}) {
  const { experimentId, targetId } = experiment;
  const { load, reload } = useReportLoad(experimentId);
  const watch = useExperimentWatch(experimentId);
  const [, navigate] = useLocation();
  const [deletion, setDeletion] = useState<
    | { status: "idle" }
    | { status: "busy" }
    | { status: "failed"; message: string }
  >({ status: "idle" });
  const plan = useMemo(() => trialPlan(specification), [specification]);
  const screen = experimentScreen(part.tab, load);

  // When the report of a run that the user watches is ready, the page moves to Report by itself,
  // and the report slides in. The mark stays while Report is on the screen.
  const [shown, setShown] = useState({ tab: screen.tab, arrived: false });
  if (shown.tab !== screen.tab)
    setShown({
      tab: screen.tab,
      arrived: arrivedAtReport(part.tab, shown.tab, screen.tab),
    });

  // The report route builds the report once evaluate completes, so read it again then.
  const kind = watch.load.status === "ready" ? watch.load.state.kind : null;
  const seen = useRef(kind);
  useEffect(() => {
    if (kind === null) return;
    if (kind === "completed" && seen.current !== null && seen.current !== kind)
      reload();
    seen.current = kind;
  }, [kind, reload]);

  const remove = () => {
    setDeletion({ status: "busy" });
    store.deleteExperiment(experimentId).then(
      () => navigate(paths.target(targetId, "experiments")),
      (cause: unknown) =>
        setDeletion({
          status: "failed",
          message: cause instanceof Error ? cause.message : String(cause),
        }),
    );
  };

  return (
    <ExperimentView
      {...experiment}
      screen={screen}
      arrived={shown.arrived}
      taskId={part.tab === "trials" ? part.taskId : null}
      load={load}
      onReload={reload}
      run={runView(
        watch.load,
        plan,
        deletion.status === "busy" ? "delete" : watch.busy,
        deletion.status === "failed" ? deletion.message : watch.actionError,
      )}
      actions={{ stop: watch.stop, resume: watch.resume, remove }}
    />
  );
}

function RunControls({
  run,
  actions,
}: {
  run: Extract<RunView, { status: "ready" }>;
  actions: RunActions;
}) {
  const [confirm, setConfirm] = useState(false);
  const on = ACTIONS[run.state.kind];
  const stopping = isLive(run.state) && run.state.stopping;
  return (
    <div className="relative flex items-center gap-2">
      {run.error !== null && (
        <p
          role="alert"
          className="absolute top-full right-0 mt-1.5 flex w-max max-w-md items-start gap-1.5 text-sm text-destructive"
        >
          <CircleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
          {run.error}
        </p>
      )}
      {on.stop && (
        <Button disabled={run.busy !== null || stopping} onClick={actions.stop}>
          <Square size={13} strokeWidth={2} aria-hidden />
          {stopping ? "Stopping" : "Stop"}
        </Button>
      )}
      {on.resume && (
        <Button
          variant="primary"
          disabled={run.busy !== null}
          onClick={actions.resume}
        >
          <RotateCcw size={13} strokeWidth={2} aria-hidden />
          Resume
        </Button>
      )}
      <Button
        disabled={!on.delete || run.busy !== null}
        title={
          on.delete ? undefined : "Stop the experiment before you delete it"
        }
        onClick={() => setConfirm(true)}
      >
        <Trash2 size={13} strokeWidth={2} aria-hidden />
        Delete
      </Button>
      {confirm && (
        <ConfirmDialog
          text="Delete this experiment? It goes from the app. Its experiment folder stays on disk."
          confirmLabel="Delete experiment"
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            actions.remove();
          }}
        />
      )}
    </div>
  );
}

// The page for one load state. It has no hook, so a test can render each state.
export function ExperimentView({
  targetId,
  targetTitle,
  experimentId,
  screen,
  arrived = false,
  taskId,
  load,
  onReload,
  run,
  actions,
}: ExperimentProps & {
  screen: ExperimentScreen;
  // True when the page moved to Report by itself, after a run that the user watched.
  arrived?: boolean;
  // The Test Case that the Trials tab shows, or null for every trial.
  taskId: string | null;
  load: ReportLoad;
  onReload: () => void;
  run: RunView;
  actions: RunActions;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* The back link, the title and the tabs are outside the scroll box, so they stay in view. */}
      <div className="flex flex-col gap-3 px-6 pt-6">
        <BackLink targetId={targetId} title={targetTitle} />
        <header className="flex items-center justify-between gap-4">
          <h1 className="flex min-w-0 items-baseline gap-2 text-xl font-semibold">
            <span className="text-sm font-normal text-muted-foreground">
              Experiment
            </span>
            <span className="truncate" title={experimentId}>
              {experimentId}
            </span>
          </h1>
          <div className="flex items-center gap-2">
            {run.status === "ready" && (
              <RunControls run={run} actions={actions} />
            )}
            {load.status === "ready" && (
              <DownloadReport experimentId={experimentId} />
            )}
          </div>
        </header>
        <div
          role="tablist"
          aria-label="Experiment"
          className="flex gap-1 border-b border-border"
        >
          {TABS.map(({ id, label }) =>
            id === "report" && screen.reportOff !== null ? (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={screen.tab === id}
                disabled
                title={screen.reportOff}
                className={cn(
                  TAB,
                  "cursor-not-allowed border-transparent text-muted-foreground opacity-45",
                )}
              >
                {label}
              </button>
            ) : (
              <Link
                key={id}
                href={paths.experiment(targetId, experimentId, id)}
                role="tab"
                aria-selected={screen.tab === id}
                className={cn(
                  TAB,
                  screen.tab === id
                    ? "border-accent text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </Link>
            ),
          )}
        </div>
      </div>
      <Page>
        {screen.tab === null ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading the experiment
          </p>
        ) : screen.tab === "trials" ? (
          run.status === "ready" ? (
            <TrialsTab
              targetId={targetId}
              experimentId={experimentId}
              state={run.state}
              rows={run.trials}
              taskId={taskId}
            />
          ) : run.status === "failed" ? (
            <p role="alert" className="text-sm text-destructive">
              {run.message}
            </p>
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              Loading the trials
            </p>
          )
        ) : (
          <div className={cn(arrived && "animate-enter-report")}>
            <ReportTab
              targetId={targetId}
              experimentId={experimentId}
              load={load}
              onReload={onReload}
            />
          </div>
        )}
      </Page>
    </div>
  );
}

export function ComparePage({
  targetId,
  targetTitle,
}: {
  targetId: string;
  targetTitle: string;
}) {
  return (
    <Page>
      <header className="flex flex-col gap-3">
        <BackLink targetId={targetId} title={targetTitle} />
        <h1 className="text-xl font-semibold">Compare experiments</h1>
      </header>
      <Placeholder>
        The experiments of this Target show here side by side.
      </Placeholder>
    </Page>
  );
}

async function everyExperiment(): Promise<ExperimentItem[]> {
  const { targets } = await store.targets();
  const lists = await Promise.all(
    targets.map(async (target) =>
      (await store.experiments(target.id)).experiments.map((record) => ({
        record,
        targetTitle: target.title,
      })),
    ),
  );
  return lists
    .flat()
    .sort((a, b) => b.record.started_at.localeCompare(a.record.started_at));
}

export function AllExperimentsPage() {
  return (
    <AllExperimentsView load={useExperimentList("all", everyExperiment)} />
  );
}

export function AllExperimentsView({ load }: { load: ListLoad }) {
  return (
    <Page>
      <h1 className="text-xl font-semibold">All experiments</h1>
      <ExperimentList load={load} />
    </Page>
  );
}
