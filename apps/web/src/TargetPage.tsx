// The tab row of a Target page, with the Run button on its right. Experiments and Run stay off
// until the Interview is done, because only then does the Target have its Specification.

import { GitCompareArrows, Play } from "lucide-react";
import { Link } from "wouter";
import { paths, type TargetTab } from "./routes";
import { Button, buttonClass, cn, Panel } from "./ui";

export const LOCKED = "Finish the Interview first";

const TAB =
  "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-150";

export function TargetTabs({
  targetId,
  tab,
  done,
  onRun,
}: {
  // Null for a new Target, which has no saved Interview yet.
  targetId: string | null;
  tab: TargetTab;
  done: boolean;
  onRun: () => void;
}) {
  const tabs: Array<{ id: TargetTab; label: string; href: string | null }> = [
    {
      id: "specification",
      label: "Specification",
      href: targetId
        ? paths.target(targetId, "specification")
        : paths.newTarget(),
    },
    {
      id: "experiments",
      label: "Experiments",
      href: targetId && done ? paths.target(targetId, "experiments") : null,
    },
  ];
  return (
    <div className="flex shrink-0 items-end justify-between gap-4 border-b border-border px-6 pt-4">
      <div role="tablist" aria-label="Target" className="flex gap-1">
        {tabs.map(({ id, label, href }) =>
          href === null ? (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={false}
              disabled
              title={LOCKED}
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
              href={href}
              role="tab"
              aria-selected={tab === id}
              className={cn(
                TAB,
                tab === id
                  ? "border-accent text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </Link>
          ),
        )}
      </div>
      <div className="mb-2">
        <Button
          variant="primary"
          disabled={!done}
          title={done ? undefined : LOCKED}
          onClick={onRun}
        >
          <Play size={14} strokeWidth={2} aria-hidden />
          Run
        </Button>
      </div>
    </div>
  );
}

export function ExperimentsTab({
  targetId,
  onRun,
}: {
  targetId: string;
  onRun: () => void;
}) {
  return (
    <div className="quiet-scrollbar min-h-0 flex-1 overflow-y-auto px-6 py-6">
      <div className="flex flex-col gap-4">
        <div className="flex justify-end">
          <Link href={paths.compare(targetId)} className={buttonClass()}>
            <GitCompareArrows size={14} strokeWidth={2} aria-hidden />
            Compare
          </Link>
        </div>
        <Panel className="flex items-center justify-between gap-3 px-5 py-4 text-sm">
          <span>No experiments yet.</span>
          <Button onClick={onRun}>Run</Button>
        </Panel>
      </div>
    </div>
  );
}
