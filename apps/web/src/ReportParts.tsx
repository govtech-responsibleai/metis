// The small parts that the Report tab and the trial drawer share.

import type { ReactNode } from "react";
import type { BehaviourRate, Outcome } from "./report";
import { cn } from "./ui";

export const OUTCOME: Record<Outcome, string> = {
  passed: "Passed",
  failed: "Failed",
  skipped: "Skipped",
  errored: "Errored",
};

// A rate, or the words for a missing rate. `className` is the class of report.html for the place.
export function RateText({
  rate,
  className,
}: {
  rate: BehaviourRate;
  className: string;
}) {
  if (rate.kind !== "measured")
    return (
      <span className={cn(className, "none")}>
        {rate.kind === "no-result" ? "No result" : "Not measured"}
      </span>
    );
  return (
    <span className={cn(className, rate.low && "low")}>{rate.percent}%</span>
  );
}

export function Tip({ children }: { children: ReactNode }) {
  return (
    <span className="ibtn" tabIndex={0} aria-label="About this">
      i<span className="tip">{children}</span>
    </span>
  );
}
