// The experiment pages. Each one says what it will show until the experiment store fills it.

import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
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

export function ExperimentPage({
  targetId,
  targetTitle,
  experimentId,
  tab,
}: {
  targetId: string;
  targetTitle: string;
  experimentId: string;
  tab: ExperimentTab;
}) {
  return (
    <Page>
      <header className="flex flex-col gap-3">
        <BackLink targetId={targetId} title={targetTitle} />
        <h1 className="text-xl font-semibold">Experiment</h1>
      </header>
      <div
        role="tablist"
        aria-label="Experiment"
        className="flex gap-1 border-b border-border"
      >
        {TABS.map(({ id, label }) => (
          <Link
            key={id}
            href={paths.experiment(targetId, experimentId, id)}
            role="tab"
            aria-selected={tab === id}
            className={cn(
              "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-150",
              tab === id
                ? "border-accent text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </Link>
        ))}
      </div>
      <Placeholder>
        {tab === "trials"
          ? "The trials of this experiment show here."
          : "The report of this experiment shows here."}
      </Placeholder>
    </Page>
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
