import assert from "node:assert/strict";
import { test } from "node:test";
import { CaseDrawerView, DRAWER_START, type DrawerState } from "./CaseDrawer";
import { ExperimentView } from "./ExperimentPages";
import { at, control, tab, text } from "./markup.test-helper";
import { experimentScreen, type ReportLoad, type ReportPage } from "./report";
import { ReportSections, SPEC_START, type SpecState } from "./ReportTab";
import { paths, type ExperimentTab } from "./routes";

const DETAIL = {
  description: "The reply starts with a greeting.",
  graderName: "GreetingGrader",
  judgeModels: ["model a", "model b"],
  passMark: 0.5,
  meanScore: 0.75,
};

const PAGE: ReportPage = {
  target: "Bank bot",
  score: {
    passRate: { kind: "measured", percent: 75, low: true },
    target: 80,
    behavioursBelowTarget: { below: 1, graded: 2 },
    trialsReached: { successful: 3, attempted: 4 },
    testCases: 2,
  },
  specification: [
    {
      id: "f1",
      name: "Onboarding",
      rate: { kind: "measured", percent: 75, low: true },
      behaviours: [
        {
          id: "b1",
          label: "Greets the user",
          statement: "The system greets the user.",
          rate: { kind: "measured", percent: 90, low: false },
          criteria: [
            {
              ...DETAIL,
              id: "c1",
              name: "Says hello",
              rate: { kind: "measured", percent: 100, low: false },
              passed: 4,
              graded: 4,
              skipped: 0,
              errored: 0,
              cases: [
                {
                  taskId: "case 1",
                  persona: "New customer",
                  scenario: "Opens an account",
                  rate: { kind: "measured", percent: 50, low: true },
                  trials: [
                    { index: 1, outcome: "passed" },
                    { index: 2, outcome: "failed" },
                  ],
                },
              ],
            },
          ],
        },
        {
          id: "b2",
          label: "Checks identity",
          statement: "The system asks for proof of identity.",
          rate: { kind: "not-measured" },
          criteria: [
            {
              ...DETAIL,
              id: "c3",
              name: "Asks for proof",
              rate: { kind: "no-result" },
              passed: 0,
              graded: 0,
              skipped: 2,
              errored: 1,
              judgeModels: [],
              passMark: null,
              meanScore: null,
              cases: [],
            },
          ],
        },
      ],
    },
  ],
  cases: {
    groups: [
      {
        featureId: "f1",
        name: "Onboarding",
        columns: [
          { criterionId: "c1", label: "Says hello" },
          { criterionId: "c3", label: "Asks for proof" },
        ],
      },
    ],
    rows: [
      {
        taskId: "case 1",
        persona: "New customer",
        scenario: "Opens an account",
        description: "A new customer opens an account.",
        trials: [
          {
            index: 1,
            category: "succeeded",
            message: "",
            failureSource: "",
            attempt: 1,
            turns: [
              { turn: 1, user: "Hello", target: "Good morning.", errors: [] },
              { turn: 2, user: "Open an account", target: null, errors: [] },
            ],
            conversationProblem: null,
            criteria: [
              {
                criterionId: "c1",
                name: "Says hello",
                outcome: "passed",
                results: [
                  {
                    outcome: "passed",
                    score: 0.75,
                    reason: "The reply starts with a greeting.",
                    measurements: [{ name: "Satisfied", value: 0.75 }],
                    passMark: 0.5,
                  },
                ],
              },
            ],
          },
          {
            index: 2,
            category: "timedOut",
            message: "The Target did not answer.",
            failureSource: "target",
            attempt: 2,
            turns: [],
            conversationProblem: "The trace is not complete",
            criteria: [
              {
                criterionId: "c1",
                name: "Says hello",
                outcome: "failed",
                results: [
                  {
                    outcome: "failed",
                    score: null,
                    reason: "The reply has no greeting.",
                    measurements: [],
                    passMark: null,
                  },
                  {
                    outcome: "failed",
                    score: 0,
                    reason: "",
                    measurements: [],
                    passMark: null,
                  },
                ],
              },
            ],
          },
        ],
        skipped: 0,
        errored: 0,
        cells: [
          {
            rate: { kind: "measured", percent: 50, low: true },
            passed: 2,
            failed: 2,
            skipped: 0,
            errored: 0,
            interval: { lower: 21, upper: 79 },
          },
          null,
        ],
      },
      {
        taskId: "case 2",
        persona: "Old customer",
        scenario: "Closes an account",
        description: "",
        trials: [],
        skipped: 2,
        errored: 1,
        cells: [
          null,
          {
            rate: { kind: "no-result" },
            passed: 0,
            failed: 0,
            skipped: 2,
            errored: 1,
            interval: null,
          },
        ],
      },
    ],
    skipped: 2,
    errored: 1,
  },
  unmapped: [],
  details: {
    run: "run 1",
    date: "2026-01-02",
    personas: 1,
    scenarios: 2,
    trials: 5,
    gradingSeconds: 12.34,
    judgeModels: ["model a", "model b"],
    unmappedRecords: 0,
    unresolvedCriteria: 0,
    schemaVersion: 1,
  },
};

// The sections of the report for one state of the specification results.
function sections(state: Partial<SpecState> = {}, page = PAGE): string {
  return at(
    paths.experiment("a", "e1", "report"),
    <ReportSections
      page={page}
      state={{ ...SPEC_START, ...state }}
      actions={{
        show: () => {},
        toggleFeature: () => {},
        toggleBehaviour: () => {},
        select: () => {},
        showCase: () => {},
        openCase: () => {},
        closeCase: () => {},
      }}
      caseHref={(taskId) => paths.testCase("a", "e1", taskId)}
    />,
  );
}

const READY: ReportLoad = { status: "ready", page: PAGE };
const NO_REPORT: ReportLoad[] = [
  { status: "loading" },
  { status: "not-evaluated" },
  { status: "not-found" },
];

function view(urlTab: ExperimentTab | null, load: ReportLoad): string {
  return at(
    paths.experiment("a", "e1", urlTab ?? undefined),
    <ExperimentView
      targetId="a"
      targetTitle="Bank bot"
      experimentId="e1"
      screen={experimentScreen(urlTab, load)}
      load={load}
      onReload={() => {}}
    />,
  );
}

test("an experiment links back to its Target and to its Trials and Report", () => {
  const markup = view("trials", READY);

  assert.match(control(markup, "Bank bot"), /href="\/targets\/a\/experiments"/);
  assert.match(
    tab(markup, "Trials"),
    /href="\/targets\/a\/experiments\/e1\/trials"/,
  );
  assert.match(tab(markup, "Trials"), /aria-selected="true"/);
  assert.match(
    tab(markup, "Report"),
    /href="\/targets\/a\/experiments\/e1\/report"/,
  );
  assert.match(tab(markup, "Report"), /aria-selected="false"/);
  assert.match(markup, /The trials of this experiment show here\./);
});

test("the Report tab control is off while the experiment has no report", () => {
  for (const load of NO_REPORT) {
    const report = tab(view(null, load), "Report");
    assert.match(report, /^<button[^>]*disabled=""/, load.status);
    assert.doesNotMatch(report, /href=/, load.status);
  }
  assert.match(
    tab(view(null, { status: "not-evaluated" }), "Report"),
    /title="The report is ready when evaluate is done"/,
  );
});

test("a bare experiment path shows a loading line while the report loads", () => {
  const markup = view(null, { status: "loading" });

  assert.match(markup, /role="status"[^>]*>Loading the experiment</);
  assert.doesNotMatch(markup, /aria-selected="true"/);
});

test("a finished experiment opens on its report", () => {
  const markup = view(null, READY);

  assert.match(tab(markup, "Report"), /aria-selected="true"/);
  assert.match(markup, /<span class="big low">75%<\/span>/);
});

test("a ready report shows the score, the specification results and the results by test case", () => {
  const shown = text(view("report", READY));

  assert.match(shown, /Behaviours below the target1 of 2/);
  assert.match(shown, /Trials that reached their goal3 of 4/);
  assert.match(shown, /Test cases2/);
  assert.match(
    shown,
    /Onboarding75%Greets the user90%Checks identityNot measuredPick a criterion/,
  );
  assert.match(
    shown,
    /Click a test case to see its trials\.2 skipped1 errored/,
  );
  assert.match(shown, /Test caseOnboardingSays helloAsks for proof/);
  assert.match(shown, /New customerOpens an account50%\(21 to 79%\)/);
  assert.match(
    shown,
    /Old customerCloses an account2 skipped1 erroredNo result/,
  );
  assert.doesNotMatch(shown, /Opens an account\d+ skipped/);
  assert.doesNotMatch(shown, /Results without a matching criterion/);
});

test("a missing number shows No result", () => {
  const shown = text(
    sections(
      {},
      {
        ...PAGE,
        score: {
          ...PAGE.score,
          passRate: { kind: "no-result" },
          behavioursBelowTarget: null,
          trialsReached: null,
        },
        details: { ...PAGE.details, gradingSeconds: null },
      },
    ),
  );

  assert.match(shown, /shown in red\.No resultBehaviours below the target/);
  assert.match(shown, /Behaviours below the targetNo result/);
  assert.match(shown, /Trials that reached their goalNo result/);
  assert.match(shown, /Grading timeNo result/);
});

test("a rate below the target is red", () => {
  const markup = sections();

  assert.match(markup, /<span class="score-val low">75%</);
  assert.match(markup, /<span class="score-val">90%</);
});

test("an open Behaviour shows its Criteria", () => {
  const shown = text(sections({ openBehaviours: new Set(["b2"]) }));

  assert.match(
    shown,
    /Greets the user90%Checks identityNot measuredAsks for proofNo result/,
  );
  assert.doesNotMatch(shown, /Says hello100%/);
});

test("a closed Feature hides its Behaviours", () => {
  const shown = text(sections({ closedFeatures: new Set(["f1"]) }));

  assert.match(shown, /Onboarding75%Pick a criterion/);
});

test("a picked Criterion shows its panel and marks its column", () => {
  const markup = sections({
    openBehaviours: new Set(["b1"]),
    selected: "c1",
  });
  const shown = text(markup);

  assert.match(
    shown,
    /OnboardingBehaviourGreets the user90%The system greets the user\./,
  );
  assert.match(
    shown,
    /CriterionSays hello100%4 of 4 graded results passedThe reply starts with a greeting\./,
  );
  assert.match(
    shown,
    /GraderGreetingGraderJudge modelmodel amodel bPass markScore ≥ 0\.50Mean score0\.75Criterion IDc1/,
  );
  assert.match(shown, /case 1New customerOpens an account50%/);
  assert.match(markup, /title="Trial 2: Failed"/);
  assert.match(markup, /<th class="crit mark"[^>]*><span>Says hello</);
  assert.match(markup, /<th class="crit"[^>]*><span>Asks for proof</);
  assert.doesNotMatch(markup, /<tr class="mark">/);
});

test("a test case of the panel marks its row and its cell in the results table", () => {
  const markup = sections({
    openBehaviours: new Set(["b1"]),
    selected: "c1",
    shownCase: "case 1",
  });

  assert.match(
    markup,
    /<tr class="mark"><th class="stick"[^>]*><button[^>]*><span class="case-name"><b>New customer</,
  );
  assert.match(
    markup,
    /<td class="cell scaled hit"[^>]*aria-label="Says hello:/,
  );
  assert.equal(markup.match(/<tr class="mark">/g)?.length, 1);
  assert.equal(markup.match(/ hit"/g)?.length, 1);
});

test("a Criterion with no threshold, score or judge model says so", () => {
  const shown = text(
    sections({ openBehaviours: new Set(["b2"]), selected: "c3" }),
  );

  assert.match(
    shown,
    /No result0 of 0 graded results passed2 skipped1 errored/,
  );
  assert.match(shown, /Judge modelNonePass markNoneMean scoreNo result/);
});

test("the tree view shows the Target, each Feature and each open level", () => {
  const markup = sections({ view: "tree", openBehaviours: new Set(["b2"]) });
  const shown = text(markup);

  assert.match(markup, /aria-label="Specification tree"/);
  assert.match(control(markup, "Tree"), /aria-pressed="true"/);
  assert.match(shown, /TARGETFEATUREBEHAVIOURCRITERION/);
  assert.match(shown, /Asks for proofNot graded/);
  assert.match(shown, /Greets the user90%/);
  assert.match(shown, /Checks identityNot measured/);
  assert.match(shown, /Onboarding75%/);
  assert.match(shown, /Bank bot75%/);
  assert.doesNotMatch(shown, /Says hello100%/);
});

// The trial drawer of one test case of the report.
function drawer(
  state: Partial<DrawerState> = {},
  marked: string | null = null,
  row = PAGE.cases.rows[0]!,
): string {
  return at(
    paths.experiment("a", "e1", "report"),
    <CaseDrawerView
      row={row}
      columns={PAGE.cases.groups.flatMap((group) => group.columns)}
      target={PAGE.score.target}
      targetName={PAGE.target}
      marked={marked}
      trialsHref={paths.testCase("a", "e1", row.taskId)}
      state={{ ...DRAWER_START, ...state }}
      onTrial={() => {}}
      onTab={() => {}}
      onClose={() => {}}
    />,
  );
}

test("a test case of the results table is a button that opens the trial drawer", () => {
  assert.match(
    control(sections(), "New customer"),
    /^<button type="button" class="case-toggle"/,
  );
});

test("the trial drawer shows the test case, the range of each Criterion and the trials", () => {
  const markup = drawer();
  const shown = text(markup);

  assert.match(
    shown,
    /Results by test caseNew customerOpens an accountOpen in the Trials tab/,
  );
  assert.ok(
    control(markup, "Open in the Trials tab").includes(
      ` href="${paths.testCase("a", "e1", "case 1")}"`,
    ),
  );
  assert.match(shown, /A new customer opens an account\./);
  assert.match(shown, /0%25%50%100%80% target/);
  assert.match(shown, /Says hello50%21 to 79%2 of 4 passed/);
  assert.doesNotMatch(shown, /Asks for proof/);
  assert.match(
    shown,
    /TrialSays helloReached its goalTrial 1HelloReached its goal2 turnsPassedTimed outTrial 2/,
  );
  assert.match(
    shown,
    /Trial 2No conversation was recorded\.Timed out: The Target did not answer\.Retried, attempt 2Failed/,
  );
  assert.match(control(markup, "Trial 1"), /aria-pressed="true"/);
  assert.match(control(markup, "Trial 2"), /aria-pressed="false"/);
});

test("the trial drawer starts on the first trial with its conversation and its grader results", () => {
  const shown = text(drawer());

  assert.match(
    shown,
    /Trial 1Turn 1UserHelloBank botGood morning\.Turn 2UserOpen an accountBank botNo reply recorded/,
  );
  assert.match(
    shown,
    /What the graders returnedPassedSays helloScore 0\.75Pass mark ≥ 0\.50Satisfied0\.75The reply starts with a greeting\./,
  );
  assert.doesNotMatch(shown, /Ended early/);
});

test("a trial that ended early says why, and each of its grader results has a number", () => {
  const markup = drawer({ trial: 2 });
  const shown = text(markup);

  assert.match(
    shown,
    /Trial 2Ended early\. Timed out: The Target did not answer\. Source: Target\. Retried, attempt 2\./,
  );
  assert.match(
    shown,
    /No conversation was recorded for this trial\. The trace is not complete\./,
  );
  assert.match(
    shown,
    /Says helloResult 1: The reply has no greeting\.Result 2: \{\s+&quot;outcome&quot;: &quot;failed&quot;,\s+&quot;score&quot;: 0\s+\}/,
  );
  assert.match(control(markup, "Trial 2"), /aria-pressed="true"/);
});

test("the trial drawer marks the picked Criterion", () => {
  const markup = drawer({}, "c1");

  assert.match(markup, /<div class="ci-row mark">/);
  assert.match(markup, /<th class="cc mark"/);
  assert.match(markup, /<div class="why-row mark">/);
});

test("a test case with no trial record says so", () => {
  const shown = text(drawer({}, null, PAGE.cases.rows[1]!));

  assert.match(shown, /Asks for proofNo resultNo result0 of 0 passed/);
  assert.match(shown, /No trial record was found for this test case\./);
});

test("a cell says its counts and its range to a screen reader", () => {
  const markup = sections();

  assert.match(
    markup,
    /aria-label="Says hello: 2 passed, 2 failed\. 95% range: 21 to 79%"/,
  );
  assert.match(
    markup,
    /aria-label="Asks for proof: 0 passed, 0 failed, 2 skipped, 1 errored"/,
  );
});

test("results without a matching Criterion have their own section", () => {
  const shown = text(
    sections(
      {},
      {
        ...PAGE,
        unmapped: [
          {
            criterionId: "c9",
            grader: "example.graders.ToneGrader",
            why: "No Task has this Criterion.",
            items: [
              {
                outcome: "failed",
                taskId: "t1",
                trialIndex: 2,
                resultNumber: 1,
                reason: "The tone is cold.",
                settings: "{}",
              },
            ],
          },
        ],
      },
    ),
  );

  assert.match(
    shown,
    /Results without a matching criterion.*c9example\.graders\.ToneGraderNo Task has this Criterion\.Failedt1trial 2result 1The tone is cold\.Recorded grader settings/,
  );
});

test("a report with no test case result says so", () => {
  const shown = text(
    sections(
      {},
      { ...PAGE, cases: { groups: [], rows: [], skipped: 0, errored: 0 } },
    ),
  );

  assert.match(shown, /0 skipped0 erroredNo test case has a grader result\./);
});

test("the run details follow the results", () => {
  const shown = text(sections());

  assert.match(
    shown,
    /Run details Runrun 1Report date2026-01-02Plan1 personas2 scenarios5 trialsGrading time12\.3 sJudge modelsmodel amodel bResults without a criterion0Unresolved criteria0report\.jsonschema version 1/,
  );
});

test("only a ready report has the download button", () => {
  assert.match(
    control(view("trials", READY), "report.html"),
    /^<button[^>]*title="The same report\.html that the CLI writes"/,
  );
  for (const load of [
    ...NO_REPORT,
    { status: "failed", message: "The build failed.", retryable: true },
  ] satisfies ReportLoad[])
    assert.doesNotMatch(view("report", load), /report\.html/, load.status);
});

test("the Report tab says that evaluate is not done", () => {
  const shown = text(view("report", { status: "not-evaluated" }));

  assert.match(shown, /This experiment has no results yet\./);
  assert.match(shown, /Run metis engine evaluate on the experiment/);
});

test("the Report tab says that the experiment is not found", () => {
  assert.match(
    view("report", { status: "not-found" }),
    /No experiment has this name\./,
  );
});

test("a failed report shows the message and a way to try again", () => {
  const failed = (retryable: boolean) =>
    view("report", {
      status: "failed",
      message: "The report build failed.",
      retryable,
    });

  assert.match(failed(true), /role="alert"[^>]*>The report build failed\.</);
  assert.match(control(failed(true), "Try again"), /^<button/);
  assert.match(tab(failed(true), "Report"), /^<a[^>]*aria-selected="true"/);
  assert.doesNotMatch(failed(false), /Try again/);
});
