// The state of an Experiment, as a chip or as plain text. A live run has an accent dot, a
// queued run shows its place in the muted style, and a stopped run has a warning icon and its
// reason as the title.

import { TriangleAlert } from "lucide-react";
import {
  isLive,
  queueText,
  STATE_LABEL,
  type ExperimentState,
} from "./experiment-status";
import { cn } from "./ui";

export function StateBadge({
  state,
  plain = false,
}: {
  state: ExperimentState;
  plain?: boolean;
}) {
  const live = isLive(state);
  const stopped = state.kind === "stopped";
  return (
    <span
      title={stopped ? (state.reason ?? undefined) : undefined}
      className={cn(
        "inline-flex items-center gap-1.5 font-medium",
        plain ? "text-sm" : "rounded-md border px-2 py-0.5 text-xs",
        stopped ? "text-warning" : !live && "text-muted-foreground",
        !plain &&
          (live
            ? "border-accent/50 bg-accent/10"
            : stopped
              ? "border-warning/50"
              : "border-border"),
      )}
    >
      {live && (
        <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
      )}
      {stopped && <TriangleAlert size={plain ? 14 : 12} aria-hidden />}
      {live && state.stopping ? "Stopping" : STATE_LABEL[state.kind]}
      {state.kind === "queued" && (
        <span className="font-normal">· {queueText(state.queueAhead)}</span>
      )}
    </span>
  );
}
