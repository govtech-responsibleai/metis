import assert from "node:assert/strict";
import { test } from "node:test";
import { NEW_EXPERIMENT, paths, placeOf } from "./routes.ts";

test("each path builder gives a path that reads back as its place", () => {
  assert.deepEqual(placeOf(paths.newTarget()), { page: "new-target" });
  assert.deepEqual(placeOf(paths.target("a")), {
    page: "target",
    targetId: "a",
    tab: null,
  });
  assert.deepEqual(placeOf(paths.target("a", "specification")), {
    page: "target",
    targetId: "a",
    tab: "specification",
  });
  assert.deepEqual(placeOf(paths.target("a", "experiments")), {
    page: "target",
    targetId: "a",
    tab: "experiments",
  });
  assert.deepEqual(placeOf(paths.experiment("a", NEW_EXPERIMENT)), {
    page: "experiment",
    targetId: "a",
    experimentId: "new",
    tab: "trials",
  });
  assert.deepEqual(placeOf(paths.experiment("a", "e1", "report")), {
    page: "experiment",
    targetId: "a",
    experimentId: "e1",
    tab: "report",
  });
  assert.deepEqual(placeOf(paths.compare("a")), {
    page: "compare",
    targetId: "a",
  });
  assert.deepEqual(placeOf(paths.experiments()), { page: "experiments" });
});

test("the root path opens a new Target", () => {
  assert.deepEqual(placeOf("/"), { page: "new-target" });
});

test("a Target id with reserved URL characters survives the round trip", () => {
  const place = placeOf(paths.target("a b/c", "specification"));
  assert.deepEqual(place, {
    page: "target",
    targetId: "a b/c",
    tab: "specification",
  });
});

test("an unknown path is not found", () => {
  for (const path of [
    "/nowhere",
    "/targets",
    "/targets/new/specification",
    "/targets/a/interview",
    "/targets/a/experiments/e1/trials",
    "/targets/a/compare/x",
    "/targets/%E0%A4%A",
  ])
    assert.deepEqual(placeOf(path), { page: "not-found" }, path);
});
