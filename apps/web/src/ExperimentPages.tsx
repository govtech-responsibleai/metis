// The experiment pages. An experiment has its report. The other pages say what they will show
// until the experiment store fills them.

import { ChevronLeft } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "wouter";
import {
  experimentScreen,
  loadReport,
  type ExperimentScreen,
  type ReportLoad,
  type SettledReportLoad,
} from "./report";
import { DownloadReport, ReportTab } from "./ReportTab";
import { paths, type ExperimentTab } from "./routes";
import { cn } from "./ui";

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

// The state holds the request of its answer, so the answer of another experiment or of an
// earlier attempt reads as loading.
function useReportLoad(experimentId: string): {
  load: ReportLoad;
  reload: () => void;
} {
  const [attempt, setAttempt] = useState(0);
  const [held, setHeld] = useState<{
    key: string;
    load: SettledReportLoad;
  } | null>(null);
  const key = `${attempt}:${experimentId}`;
  useEffect(() => {
    let current = true;
    void loadReport(experimentId).then((load) => {
      if (current) setHeld({ key, load });
    });
    return () => {
      current = false;
    };
  }, [experimentId, key]);
  return {
    load: held?.key === key ? held.load : LOADING,
    reload: () => setAttempt((count) => count + 1),
  };
}

interface ExperimentProps {
  targetId: string;
  targetTitle: string;
  experimentId: string;
}

export function ExperimentPage({
  tab,
  ...experiment
}: ExperimentProps & {
  // Null for the bare experiment URL.
  tab: ExperimentTab | null;
}) {
  const { load, reload } = useReportLoad(experiment.experimentId);
  return (
    <ExperimentView
      {...experiment}
      screen={experimentScreen(tab, load)}
      load={load}
      onReload={reload}
    />
  );
}

// The page for one load state. It has no hook, so a test can render each state.
export function ExperimentView({
  targetId,
  targetTitle,
  experimentId,
  screen,
  load,
  onReload,
}: ExperimentProps & {
  screen: ExperimentScreen;
  load: ReportLoad;
  onReload: () => void;
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
          {load.status === "ready" && (
            <DownloadReport experimentId={experimentId} />
          )}
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
          <Placeholder>The trials of this experiment show here.</Placeholder>
        ) : (
          <ReportTab
            targetId={targetId}
            experimentId={experimentId}
            load={load}
            onReload={onReload}
          />
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

export function AllExperimentsPage() {
  return (
    <Page>
      <h1 className="text-xl font-semibold">All experiments</h1>
      <Placeholder>The experiments of every Target show here.</Placeholder>
    </Page>
  );
}
