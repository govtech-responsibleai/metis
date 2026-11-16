import assert from "node:assert/strict";
import { test } from "node:test";
import { NEW_EXPERIMENT, paths, placeOf, targetRedirect } from "./routes.ts";

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
  assert.deepEqual(placeOf(paths.experiment("a", "e1", "trials")), {
    page: "experiment",
    targetId: "a",
    experimentId: "e1",
    tab: "trials",
    taskId: null,
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

test("a bare experiment path has no tab", () => {
  assert.equal(
    paths.experiment("a", NEW_EXPERIMENT),
    "/targets/a/experiments/new",
  );
  assert.deepEqual(placeOf(paths.experiment("a", NEW_EXPERIMENT)), {
    page: "experiment",
    targetId: "a",
    experimentId: "new",
    tab: null,
  });
});

test("a test case path opens the Trials tab at that test case", () => {
  assert.deepEqual(placeOf(paths.testCase("a", "e1", "case 1/2")), {
    page: "experiment",
    targetId: "a",
    experimentId: "e1",
    tab: "trials",
    taskId: "case 1/2",
  });
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

test("a Target opens its Experiments tab when its Interview is done", () => {
  assert.equal(
    targetRedirect(placeOf("/targets/a"), true),
    "/targets/a/experiments",
  );
  assert.equal(
    targetRedirect(placeOf("/targets/a"), false),
    "/targets/a/specification",
  );
});

test("an unfinished Target sends every place but its Specification tab there", () => {
  for (const path of [
    paths.target("a", "experiments"),
    paths.experiment("a", NEW_EXPERIMENT),
    paths.experiment("a", "e1", "report"),
    paths.testCase("a", "e1", "c1"),
    paths.compare("a"),
  ])
    assert.equal(
      targetRedirect(placeOf(path), false),
      "/targets/a/specification",
      path,
    );
  assert.equal(
    targetRedirect(placeOf(paths.target("a", "specification")), false),
    null,
  );
});

test("a done Target stays on the place that its URL names", () => {
  for (const path of [
    paths.target("a", "specification"),
    paths.target("a", "experiments"),
    paths.experiment("a", "e1"),
    paths.experiment("a", "e1", "report"),
    paths.testCase("a", "e1", "c1"),
    paths.compare("a"),
  ])
    assert.equal(targetRedirect(placeOf(path), true), null, path);
});

test("an unknown path is not found", () => {
  for (const path of [
    "/nowhere",
    "/targets",
    "/targets/new/specification",
    "/targets/a/interview",
    "/targets/a/experiments/e1/results",
    "/targets/a/experiments/e1/report/c1",
    "/targets/a/experiments/e1/trials/c1/x",
    "/targets/a/compare/x",
    "/targets/%E0%A4%A",
  ])
    assert.deepEqual(placeOf(path), { page: "not-found" }, path);
});
