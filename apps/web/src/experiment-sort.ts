import type { ExperimentState } from "./experiment-status.ts";
import type { ListRow } from "./ExperimentList.tsx";

export type SortKey = "id" | "started" | "updated" | "status";

export type Direction = "ascending" | "descending";

export interface Sort {
  key: SortKey;
  direction: Direction;
}

export const DEFAULT_SORT: Sort = { key: "started", direction: "descending" };

// Ascending puts the live runs first.
const STATUS_RANK: Record<ExperimentState["kind"], number> = {
  simulating: 0,
  evaluating: 1,
  queued: 2,
  waiting: 3,
  stopped: 4,
  completed: 5,
};

// `value` is null for a row whose status has not loaded. Such a row goes after the others in
// both directions, so a fresh load never moves to the top.
export const SORT_COLUMNS: Record<
  SortKey,
  {
    label: string;
    first: Direction;
    value: (row: ListRow) => string | number | null;
  }
> = {
  id: {
    label: "Experiment ID",
    first: "ascending",
    value: (row) => row.record.experiment_id,
  },
  started: {
    label: "Started",
    first: "descending",
    value: (row) => Date.parse(row.record.started_at),
  },
  updated: {
    label: "Last updated",
    first: "descending",
    value: (row) =>
      row.load.status === "ready" ? Date.parse(row.load.updatedAt) : null,
  },
  status: {
    label: "Status",
    first: "ascending",
    value: (row) =>
      row.load.status === "ready" ? STATUS_RANK[row.load.state.kind] : null,
  },
};

export function nextSort(current: Sort, key: SortKey): Sort {
  if (current.key !== key) return { key, direction: SORT_COLUMNS[key].first };
  return {
    key,
    direction: current.direction === "ascending" ? "descending" : "ascending",
  };
}

function order(a: string | number, b: string | number): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function sortRows<Row extends ListRow>(
  rows: readonly Row[],
  sort: Sort,
): Row[] {
  const { value } = SORT_COLUMNS[sort.key];
  const sign = sort.direction === "ascending" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const [left, right] = [value(a), value(b)];
    if (left === null || right === null) {
      if (left !== right) return left === null ? 1 : -1;
    } else {
      const compared = order(left, right);
      if (compared !== 0) return sign * compared;
    }
    return (
      order(Date.parse(b.record.started_at), Date.parse(a.record.started_at)) ||
      order(a.record.experiment_id, b.record.experiment_id)
    );
  });
}
