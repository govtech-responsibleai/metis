// The end of the interview, marked in the conversation. Download remains available from the
// completed Specification pane. "Connect target" adds or replaces the target binding.

import { PartyPopper } from "lucide-react";
import type { TargetConnection } from "./transport/api";
import { Button, Panel } from "./ui";

export function Done({
  connection = null,
  onConnect,
  onBack,
  busy = false,
}: {
  connection?: TargetConnection | null;
  onConnect?: () => void;
  // Reopens the last review of the Interview.
  onBack?: () => void;
  busy?: boolean;
}) {
  return (
    // Reaching the end is a state worth marking, but not with a coloured left-rule — that reads
    // as generated chrome and breaks the borders-not-accents rule. The panel stays a plain
    // bordered card; the accent lands only on the heading and its icon, where "ready" is the state
    // being signalled.
    <Panel className="flex flex-col gap-2 p-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-accent">
        <PartyPopper size={18} strokeWidth={1.75} aria-hidden />
        Your specification is ready
      </h2>
      <p className="text-sm text-muted-foreground">
        Download the complete specification ZIP.{" "}
        {connection
          ? `It includes the ${connection.transport === "http" ? "HTTP" : "browser"} target binding${connection.status === "checked" ? "" : ", which was not checked"}.`
          : "It has no target binding, so the Engine uses the default runner."}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {onBack && (
          <Button type="button" disabled={busy} onClick={onBack}>
            ← Back
          </Button>
        )}
        {onConnect && (
          <Button type="button" onClick={onConnect}>
            {connection ? "Change target connection" : "Connect target"}
          </Button>
        )}
      </div>
    </Panel>
  );
}
