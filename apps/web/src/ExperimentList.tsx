import { ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import {
  experimentState,
  progressText,
  type ExperimentState,
} from "./experiment-status";
import { relativeTime } from "./relative-time";
import { paths } from "./routes";
import { StateBadge } from "./StateBadge";
import { api, type ExperimentRecord } from "./transport/api";
import { cn, Panel } from "./ui";

export interface ExperimentItem {
  record: ExperimentRecord;
  // The title of the Target, for a list that holds the Experiments of more than one Target.
  targetTitle?: string;
}

export type RowLoad =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "ready"; state: ExperimentState };

export type ListLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; rows: Array<ExperimentItem & { load: RowLoad }> };

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

async function rowLoad({ experiment_id, step }: ExperimentRecord) {
  try {
    const [status, events] = await Promise.all([
      api.engineStatus(experiment_id),
      api.engineEvents(experiment_id),
    ]);
    return {
      status: "ready",
      state: experimentState(step, status, events),
    } as const;
  } catch {
    return { status: "failed" } as const;
  }
}

// Reads the rows from `read`, then the state of each row from the engine routes. `key` names
// the source, so a new key reads again.
export function useExperimentList(
  key: string,
  read: () => Promise<ExperimentItem[]>,
): ListLoad {
  const [held, setHeld] = useState<{ key: string; load: ListLoad } | null>(
    null,
  );
  const reader = useRef(read);
  reader.current = read;
  useEffect(() => {
    let current = true;
    const show = (load: ListLoad) => {
      if (current) setHeld({ key, load });
    };
    void reader.current().then(
      async (items) => {
        const rows = items.map((item) => ({
          ...item,
          load: { status: "loading" } as RowLoad,
        }));
        show({ status: "ready", rows });
        const loads = await Promise.all(
          items.map((item) => rowLoad(item.record)),
        );
        show({
          status: "ready",
          rows: rows.map((row, index) => ({
            ...row,
            load: loads[index] ?? row.load,
          })),
        });
      },
      (cause: unknown) => show({ status: "failed", message: errorText(cause) }),
    );
    return () => {
      current = false;
    };
  }, [key, reader]);
  return held?.key === key ? held.load : { status: "loading" };
}

export function ExperimentList({ load }: { load: ListLoad }) {
  if (load.status === "loading")
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading the experiments
      </p>
    );
  if (load.status === "failed")
    return (
      <p role="alert" className="text-sm text-destructive">
        {load.message}
      </p>
    );
  if (load.rows.length === 0)
    return <p className="text-sm text-muted-foreground">No experiments yet.</p>;
  return (
    <Panel className="overflow-hidden">
      <ul>
        {load.rows.map((row) => (
          <li
            key={row.record.experiment_id}
            className="border-b border-border last:border-b-0"
          >
            <ExperimentRow {...row} />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ExperimentRow({
  record,
  targetTitle,
  load,
}: ExperimentItem & { load: RowLoad }) {
  return (
    <Link
      href={paths.experiment(record.target_id, record.experiment_id)}
      className={cn(
        "grid w-full items-center gap-4 px-4 py-3 text-sm transition-colors duration-150 hover:bg-muted",
        targetTitle === undefined
          ? "grid-cols-[8rem_12rem_minmax(0,1fr)_auto]"
          : "grid-cols-[minmax(0,1.2fr)_8rem_12rem_minmax(0,1fr)_auto]",
      )}
    >
      {targetTitle !== undefined && (
        <span className="truncate font-semibold">{targetTitle}</span>
      )}
      <time
        dateTime={record.started_at}
        title={new Date(record.started_at).toLocaleString()}
        className={cn(targetTitle === undefined && "font-semibold")}
      >
        {relativeTime(Date.parse(record.started_at))}
      </time>
      <span>
        {load.status === "ready" ? (
          <StateBadge state={load.state} />
        ) : load.status === "failed" ? (
          <span className="text-muted-foreground">Status unavailable</span>
        ) : null}
      </span>
      <span className="tabular-nums text-muted-foreground">
        {load.status === "ready" && progressText(load.state.progress)}
      </span>
      <ChevronRight size={14} className="text-muted-foreground" aria-hidden />
    </Link>
  );
}
