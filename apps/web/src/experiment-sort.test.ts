import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT_SORT,
  nextSort,
  sortRows,
  type Sort,
} from "./experiment-sort.ts";
import type { ExperimentState } from "./experiment-status.ts";
import type { ListRow, RowLoad } from "./ExperimentList.tsx";

const at = (time: string) => `2026-11-19T${time}:00Z`;

const ready = (kind: ExperimentState["kind"], updated: string): RowLoad => ({
  status: "ready",
  state: { kind, progress: null } as ExperimentState,
  updatedAt: at(updated),
});

const row = (id: string, started: string, load: RowLoad): ListRow => ({
  record: {
    experiment_id: id,
    target_id: "t",
    started_at: at(started),
    step: "simulate",
  },
  load,
});

const ROWS: readonly ListRow[] = [
  row("e-a", "10:00", ready("simulating", "10:30")),
  row("e-b", "10:05", ready("completed", "10:10")),
  row("e-c", "09:00", ready("stopped", "11:00")),
  row("e-d", "10:05", { status: "loading" }),
  row("e-0", "08:00", { status: "failed" }),
];

const ids = (sort: Sort, rows = ROWS) =>
  sortRows(rows, sort).map((item) => item.record.experiment_id);

test("the default order is the newest start first", () => {
  assert.deepEqual(ids(DEFAULT_SORT), ["e-b", "e-d", "e-a", "e-c", "e-0"]);
});

test("each column sorts both ways, with rows that have no status after the others", () => {
  const both = (key: Sort["key"]) => ({
    ascending: ids({ key, direction: "ascending" }),
    descending: ids({ key, direction: "descending" }),
  });

  assert.deepEqual(both("id"), {
    ascending: ["e-0", "e-a", "e-b", "e-c", "e-d"],
    descending: ["e-d", "e-c", "e-b", "e-a", "e-0"],
  });
  assert.deepEqual(both("started"), {
    ascending: ["e-0", "e-c", "e-a", "e-b", "e-d"],
    descending: ["e-b", "e-d", "e-a", "e-c", "e-0"],
  });
  assert.deepEqual(both("updated"), {
    ascending: ["e-b", "e-a", "e-c", "e-d", "e-0"],
    descending: ["e-c", "e-a", "e-b", "e-d", "e-0"],
  });
  assert.deepEqual(both("status"), {
    ascending: ["e-a", "e-c", "e-b", "e-d", "e-0"],
    descending: ["e-b", "e-c", "e-a", "e-d", "e-0"],
  });
});

test("rows that tie keep the newest start first, then the Experiment ID", () => {
  const tied = [
    row("e-2", "10:00", ready("completed", "12:00")),
    row("e-3", "11:00", ready("completed", "12:00")),
    row("e-1", "10:00", ready("completed", "12:00")),
  ];

  for (const direction of ["ascending", "descending"] as const)
    assert.deepEqual(ids({ key: "status", direction }, tied), [
      "e-3",
      "e-1",
      "e-2",
    ]);
});

test("a click on the sorted column turns it round, and a click on another column starts at its first direction", () => {
  assert.deepEqual(nextSort(DEFAULT_SORT, "started"), {
    key: "started",
    direction: "ascending",
  });
  assert.deepEqual(nextSort(DEFAULT_SORT, "id"), {
    key: "id",
    direction: "ascending",
  });
  assert.deepEqual(nextSort(DEFAULT_SORT, "status"), {
    key: "status",
    direction: "ascending",
  });
  assert.deepEqual(nextSort({ key: "id", direction: "ascending" }, "updated"), {
    key: "updated",
    direction: "descending",
  });
});

test("sorting gives a new list and keeps the input order", () => {
  const rows = [...ROWS];

  const sorted = sortRows(rows, { key: "id", direction: "ascending" });

  assert.notEqual(sorted, rows);
  assert.deepEqual(rows, ROWS);
});
