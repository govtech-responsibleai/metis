// The Experiments of one Target as a table that sorts by a column. The Experiment ID is the
// link for the keyboard. A click elsewhere on the row goes to the same place.

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "wouter";
import {
  DEFAULT_SORT,
  nextSort,
  SORT_COLUMNS,
  sortRows,
  type Direction,
  type Sort,
  type SortKey,
} from "./experiment-sort";
import { progressText } from "./experiment-status";
import { ListStates, type ListLoad, type ListRow } from "./ExperimentList";
import { absoluteTime, relativeTime } from "./relative-time";
import { paths } from "./routes";
import { StateBadge } from "./StateBadge";
import { cn, Panel } from "./ui";

const ARROW: Record<Direction, LucideIcon> = {
  ascending: ArrowUp,
  descending: ArrowDown,
};

const SORTED_COLUMNS = Object.keys(SORT_COLUMNS) as SortKey[];

export function ExperimentTable({ load }: { load: ListLoad }) {
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  return (
    <ListStates load={load}>
      {(rows) => (
        <Panel className="overflow-hidden">
          <table className="w-full table-fixed text-sm">
            <colgroup>
              <col />
              <col className="w-[10.5rem]" />
              <col className="w-[10.5rem]" />
              <col className="w-[12rem]" />
              <col className="w-[10rem]" />
              <col className="w-10" />
            </colgroup>
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-muted-foreground">
                {SORTED_COLUMNS.map((key, index) => (
                  <SortHeader
                    key={key}
                    column={key}
                    sort={sort}
                    first={index === 0}
                    onSort={() => setSort(nextSort(sort, key))}
                  />
                ))}
                <th className="px-2 py-2.5 font-medium">Progress</th>
                <th aria-hidden />
              </tr>
            </thead>
            <tbody>
              {sortRows(rows, sort).map((row) => (
                <ExperimentRow key={row.record.experiment_id} {...row} />
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </ListStates>
  );
}

function SortHeader({
  column,
  sort,
  first,
  onSort,
}: {
  column: SortKey;
  sort: Sort;
  first: boolean;
  onSort: () => void;
}) {
  const active = sort.key === column;
  const Icon = active ? ARROW[sort.direction] : ArrowUpDown;
  return (
    <th
      aria-sort={active ? sort.direction : undefined}
      className={cn("py-1.5 font-medium", first ? "pl-2.5 pr-2" : "px-0.5")}
    >
      <button
        type="button"
        onClick={onSort}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm px-1.5 py-1 transition-colors duration-150 hover:text-foreground",
          active && "text-foreground",
        )}
      >
        {SORT_COLUMNS[column].label}
        <Icon
          size={14}
          aria-hidden
          className={cn(!active && "text-muted-foreground/60")}
        />
      </button>
    </th>
  );
}

function ExperimentRow({ record, load }: ListRow) {
  const [, navigate] = useLocation();
  const href = paths.experiment(record.target_id, record.experiment_id);
  return (
    <tr
      onClick={(event) => {
        if (!(event.target as Element).closest("a")) navigate(href);
      }}
      className="cursor-pointer border-b border-border transition-colors duration-150 last:border-b-0 hover:bg-muted"
    >
      <td className="truncate px-4 py-2.5">
        <Link
          href={href}
          title={record.experiment_id}
          className="font-mono text-xs tracking-tight"
        >
          {record.experiment_id}
        </Link>
      </td>
      <td className="px-2 py-2.5">
        <TimeCell at={record.started_at} />
      </td>
      <td className="px-2 py-2.5">
        {load.status === "ready" && <TimeCell at={load.updatedAt} />}
      </td>
      <td className="px-2 py-2.5">
        {load.status === "ready" ? (
          <StateBadge state={load.state} />
        ) : load.status === "failed" ? (
          <span className="text-muted-foreground">Status unavailable</span>
        ) : null}
      </td>
      <td className="px-2 py-2.5 tabular-nums text-muted-foreground">
        {load.status === "ready" && progressText(load.state.progress)}
      </td>
      <td className="px-2 py-2.5 text-muted-foreground">
        <ChevronRight size={14} aria-hidden />
      </td>
    </tr>
  );
}

function TimeCell({ at }: { at: string }) {
  const time = Date.parse(at);
  return (
    <time dateTime={at} title={relativeTime(time)} className="tabular-nums">
      {absoluteTime(time)}
    </time>
  );
}
