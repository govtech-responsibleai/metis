import assert from "node:assert/strict";
import { test } from "node:test";
import {
  experimentScreen,
  loadReport,
  reportPage,
  type ReportLoad,
} from "./report.ts";
import { TransportError, type Report } from "./transport/api.ts";

type Behaviour = Report["behaviours"][string];
type Criterion = Report["criteria"][string];
type CaseResult = NonNullable<
  Report["resultTable"]["rows"][number]["results"]
>[string];

const counts = { pass: 0, fail: 0, skip: 0, error: 0 };

function behaviour(overrides: Partial<Behaviour>): Behaviour {
  return {
    ...counts,
    label: "Greets the user",
    statement: "",
    detail: "",
    priority: true,
    criteria: ["c1"],
    rate: 90,
    ...overrides,
  };
}

function criterion(overrides: Partial<Criterion>): Criterion {
  return {
    ...counts,
    name: "Says hello",
    description: "",
    grader_name: "GreetingGrader",
    rate: 90,
    ...overrides,
  };
}

function result(overrides: Partial<CaseResult>): CaseResult {
  return { ...counts, evaluated: 0, rate: 100, ...overrides };
}

// A small report: one Feature with two Behaviours, three Criteria, and two test cases.
function report(overrides: Partial<Report> = {}): Report {
  return {
    passRateTarget: 80,
    scores: { graderPassRate: { ...counts, rate: 75 } },
    trials: { attempted: 4, successful: 3 },
    plan: { tasks: [{ id: "t1" }, { id: "t2" }] },
    names: { P: { p1: "New customer" }, S: { s1: "Opens an account" } },
    features: [
      {
        ...counts,
        id: "f1",
        name: "Onboarding",
        behaviours: ["b1", "b2"],
        rate: 75,
      },
    ],
    behaviours: {
      b1: behaviour({ criteria: ["c1", "c2"], rate: 90 }),
      b2: behaviour({ label: "Checks identity", criteria: ["c3"], rate: 60 }),
    },
    criteria: {
      c1: criterion({ rate: 100, pass: 4 }),
      c2: criterion({ name: "Uses the name", rate: 80, pass: 4, fail: 1 }),
      c3: criterion({ name: "Asks for proof", rate: 60, pass: 3, fail: 2 }),
    },
    resultTable: {
      features: [
        {
          id: "f1",
          name: "Onboarding",
          columns: [
            { criterion: "c1", grader_name: "GreetingGrader" },
            { criterion: "c3", grader_name: "ProofGrader" },
          ],
        },
      ],
      rows: [
        {
          task_id: "t1",
          persona: "p1",
          scenario: "s1",
          results: { c1: result({ rate: 100 }), c3: result({ rate: 50 }) },
        },
      ],
    },
    unmapped: [],
    ...overrides,
  } as unknown as Report;
}

const READY: ReportLoad = { status: "ready", page: reportPage(report()) };
const LOADS: ReportLoad[] = [
  { status: "loading" },
  READY,
  { status: "not-evaluated" },
  { status: "not-found" },
  { status: "failed", message: "The build failed.", retryable: false },
];

test("a finished experiment opens on Report", () => {
  assert.deepEqual(experimentScreen(null, READY), {
    tab: "report",
    reportOff: null,
  });
});

test("an experiment without a report opens on Trials", () => {
  for (const load of LOADS.slice(2))
    assert.equal(experimentScreen(null, load).tab, "trials", load.status);
});

test("a bare experiment path shows no tab while the report loads", () => {
  assert.equal(experimentScreen(null, { status: "loading" }).tab, null);
});

test("the Report tab is off until evaluate is done", () => {
  assert.deepEqual(
    LOADS.map((load) => [load.status, experimentScreen(null, load).reportOff]),
    [
      ["loading", "The report is loading"],
      ["ready", null],
      ["not-evaluated", "The report is ready when evaluate is done"],
      ["not-found", "This experiment has no report"],
      ["failed", null],
    ],
  );
});

test("a tab that the URL names stays open in every load state", () => {
  for (const load of LOADS) {
    assert.equal(experimentScreen("trials", load).tab, "trials", load.status);
    assert.equal(experimentScreen("report", load).tab, "report", load.status);
  }
});

test("a report from the route is ready", async () => {
  const asked: string[] = [];
  const load = await loadReport("e1", async (experimentId) => {
    asked.push(experimentId);
    return report();
  });

  assert.deepEqual(asked, ["e1"]);
  assert.deepEqual(load, READY);
});

test("missing results mean that evaluate is not done", async () => {
  const load = await loadReport("e1", async () => {
    throw new TransportError("No results.", {
      status: 409,
      code: "results_missing",
    });
  });

  assert.deepEqual(load, { status: "not-evaluated" });
});

test("an unknown experiment is not found", async () => {
  const load = await loadReport("e1", async () => {
    throw new TransportError("No folder.", {
      status: 404,
      code: "experiment_not_found",
    });
  });

  assert.deepEqual(load, { status: "not-found" });
});

test("another failure keeps the message of the API", async () => {
  const build = await loadReport("e1", async () => {
    throw new TransportError("The report build failed.", {
      status: 409,
      code: "report_build_failed",
    });
  });
  const network = await loadReport("e1", async () => {
    throw new TransportError("Couldn't reach the METIS API.", {
      retryable: true,
    });
  });

  assert.deepEqual(build, {
    status: "failed",
    message: "The report build failed.",
    retryable: false,
  });
  assert.deepEqual(network, {
    status: "failed",
    message: "Couldn't reach the METIS API.",
    retryable: true,
  });
});

test("the score has the pass rate, the target and the number of test cases", () => {
  const { score } = reportPage(report());

  assert.deepEqual(score.passRate, {
    kind: "measured",
    percent: 75,
    low: true,
  });
  assert.equal(score.target, 80);
  assert.equal(score.testCases, 2);
  assert.deepEqual(score.trialsReached, { successful: 3, attempted: 4 });
});

test("Behaviours below the target are counted among the Behaviours with a rate", () => {
  const { score } = reportPage(
    report({
      features: [
        { ...report().features[0]!, behaviours: ["b1", "b2", "b3", "gone"] },
      ],
      behaviours: {
        b1: behaviour({ rate: 90 }),
        b2: behaviour({ rate: 60 }),
        b3: behaviour({ rate: null }),
        other: behaviour({ rate: 10 }),
      },
    }),
  );

  assert.deepEqual(score.behavioursBelowTarget, { below: 1, graded: 2 });
});

test("a score fact with nothing to count has no value", () => {
  const { score } = reportPage(
    report({
      behaviours: { b1: behaviour({ rate: null }) },
      trials: { attempted: 0, successful: 0 },
    }),
  );

  assert.equal(score.behavioursBelowTarget, null);
  assert.equal(score.trialsReached, null);
});

test("the specification list follows the order of the report", () => {
  const { specification } = reportPage(
    report({
      behaviours: {
        b2: behaviour({ label: "Checks identity", criteria: ["c3", "gone"] }),
        b1: behaviour({ criteria: ["c2", "c1"] }),
      },
    }),
  );

  assert.deepEqual(
    specification.map((feature) => [
      feature.id,
      feature.name,
      feature.behaviours.map((b) => [
        b.id,
        b.label,
        b.criteria.map((c) => c.id),
      ]),
    ]),
    [
      [
        "f1",
        "Onboarding",
        [
          ["b1", "Greets the user", ["c2", "c1"]],
          ["b2", "Checks identity", ["c3"]],
        ],
      ],
    ],
  );
});

test("a Behaviour with no priority or no Criteria is not measured", () => {
  const { specification } = reportPage(
    report({
      behaviours: {
        b1: behaviour({ priority: false, rate: 90 }),
        b2: behaviour({ criteria: [], rate: 90 }),
      },
    }),
  );

  assert.deepEqual(
    specification[0]?.behaviours.map((b) => b.rate),
    [{ kind: "not-measured" }, { kind: "not-measured" }],
  );
});

test("a rate below the target is low", () => {
  const [feature] = reportPage(report()).specification;

  assert.deepEqual(feature?.rate, { kind: "measured", percent: 75, low: true });
  assert.deepEqual(
    feature?.behaviours.map((b) => b.rate),
    [
      { kind: "measured", percent: 90, low: false },
      { kind: "measured", percent: 60, low: true },
    ],
  );
  assert.deepEqual(feature?.behaviours[0]?.criteria[1]?.rate, {
    kind: "measured",
    percent: 80,
    low: false,
  });
});

test("a missing rate has no result", () => {
  const { scores } = report();
  const page = reportPage(
    report({
      scores: {
        ...scores,
        graderPassRate: { ...scores.graderPassRate, rate: null },
      },
      criteria: { c1: criterion({ rate: null }) },
    }),
  );

  assert.deepEqual(page.score.passRate, { kind: "no-result" });
  assert.deepEqual(page.specification[0]?.behaviours[0]?.criteria[0]?.rate, {
    kind: "no-result",
  });
});

test("a Criterion has its counts of passed, graded, skipped and errored results", () => {
  const { specification } = reportPage(
    report({
      criteria: {
        c1: criterion({ pass: 3, fail: 2, skip: 1, error: 4 }),
      },
    }),
  );

  assert.deepEqual(specification[0]?.behaviours[0]?.criteria[0], {
    id: "c1",
    name: "Says hello",
    rate: { kind: "measured", percent: 90, low: false },
    passed: 3,
    graded: 5,
    skipped: 1,
    errored: 4,
  });
});

test("the table has one column for each Criterion of a Feature with columns", () => {
  const { cases } = reportPage(
    report({
      resultTable: {
        features: [
          ...report().resultTable.features,
          { id: "f2", name: "Payments", columns: [] },
          {
            id: "f3",
            name: "Support",
            columns: [{ criterion: "c9", grader_name: "ToneGrader" }],
          },
        ],
        rows: [],
      },
    }),
  );

  assert.deepEqual(cases.groups, [
    {
      featureId: "f1",
      name: "Onboarding",
      columns: [
        { criterionId: "c1", label: "Says hello" },
        { criterionId: "c3", label: "Asks for proof" },
      ],
    },
    {
      featureId: "f3",
      name: "Support",
      columns: [{ criterionId: "c9", label: "c9" }],
    },
  ]);
});

test("a test case shows the names of its Persona and Scenario", () => {
  const row = { task_id: "t2", persona: "p9", scenario: "s9" };
  const { rows } = reportPage(
    report({
      resultTable: {
        ...report().resultTable,
        rows: [...report().resultTable.rows, row],
      },
    }),
  ).cases;

  assert.deepEqual(
    rows.map(({ taskId, persona, scenario }) => [taskId, persona, scenario]),
    [
      ["t1", "New customer", "Opens an account"],
      ["t2", "p9", "s9"],
    ],
  );
});

test("a test case sums its skipped and errored results", () => {
  const { rows } = reportPage(
    report({
      resultTable: {
        ...report().resultTable,
        rows: [
          {
            task_id: "t1",
            persona: "p1",
            scenario: "s1",
            results: {
              c1: result({ skip: 1, error: 2 }),
              c3: result({ skip: 3 }),
            },
          },
        ],
      },
    }),
  ).cases;

  assert.equal(rows[0]?.skipped, 4);
  assert.equal(rows[0]?.errored, 2);
});

test("a cell has the rate and the rounded confidence interval", () => {
  const { rows } = reportPage(
    report({
      resultTable: {
        ...report().resultTable,
        rows: [
          {
            task_id: "t1",
            persona: "p1",
            scenario: "s1",
            results: {
              c3: result({
                rate: 50,
                confidence_interval: {
                  method: "wilson",
                  confidence_level: 0.95,
                  lower: 0.2065,
                  upper: 0.7935,
                },
              }),
            },
          },
          {
            task_id: "t2",
            persona: "p1",
            scenario: "s1",
            results: { c1: result({ rate: null }) },
          },
        ],
      },
    }),
  ).cases;

  assert.deepEqual(
    rows.map((row) => row.cells),
    [
      [
        null,
        {
          rate: { kind: "measured", percent: 50, low: true },
          interval: { lower: 21, upper: 79 },
        },
      ],
      [{ rate: { kind: "no-result" }, interval: null }, null],
    ],
  );
});

test("results without a matching Criterion are listed", () => {
  const { unmapped } = reportPage(
    report({
      unmapped: [
        {
          ...counts,
          grader_fqn: "example.graders.ToneGrader",
          criterion_id: "c9",
          grader_name: "ToneGrader",
          why: "No Task has this Criterion.",
        },
      ],
    }),
  );

  assert.deepEqual(unmapped, [
    {
      criterionId: "c9",
      graderName: "ToneGrader",
      why: "No Task has this Criterion.",
    },
  ]);
});
