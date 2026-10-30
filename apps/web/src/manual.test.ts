import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { GraderSpec } from "./transport/api.ts";
import {
  deselectGrader,
  emptyManualExperiment,
  emptyManualTestCase,
  keepReferencedFixtures,
  manualFieldErrors,
  replaceTaskReference,
  graderGroups,
  selectGrader,
  synthesizeManualSpecification,
  updateGrader,
  type ManualExperiment,
  type ManualGrader,
} from "./manual.ts";

const synthesisGrader = {
  fqn: "tests.unit.engine.graders_for_tests.FixedScoreGrader",
  name: "Synthesis faithfulness",
  description: "Checks that the answer uses its evidence.",
  uses_criterion_description: false,
};
const budgetGrader: GraderSpec = {
  fqn: "metis.library.graders.demo.DemoTraceBudgetGrader",
  name: "Turn budget",
  description: "Checks that the conversation stays within its turn budget.",
  uses_criterion_description: false,
  settings: [
    { name: "max_traces", kind: "integer", required: false, base: false },
  ],
};
const selected = (grader: GraderSpec): ManualGrader => ({
  spec: grader,
  description: `${grader.name}: ${grader.description}`,
  values: {},
});
const synthesis = {
  id: " manual-research ",
  description: " Check research answers and recovery. ",
  personas: [
    { id: " analyst ", description: " A careful policy analyst. " },
    { id: "director", description: "A time-poor director." },
  ],
  scenarios: [
    { id: " supported-answer ", description: " Ask for a supported answer. " },
    { id: "short-recovery", description: "Recover after a failed search." },
  ],
  tasks: [
    {
      id: "",

      scenario_ref: "supported-answer",
      persona_ref: "analyst",
      num_trials: 2,
      fixtures: ["policy.pdf"],
      graders: [selected(synthesisGrader), selected(budgetGrader)],
    },
    {
      id: "",

      scenario_ref: "supported-answer",
      persona_ref: "director",
      num_trials: 2,
      fixtures: ["policy.pdf"],
      graders: [selected(synthesisGrader), selected(budgetGrader)],
    },
    {
      id: "",

      scenario_ref: "short-recovery",
      persona_ref: "analyst",
      num_trials: 1,
      fixtures: ["notes.txt"],
      graders: [selected(budgetGrader)],
    },
  ],
} satisfies ManualExperiment;

test("explicit test cases produce the complete engine Specification", () => {
  const expected = JSON.parse(
    readFileSync(
      new URL(
        "../../../tests/fixtures/wizard/manual_specification.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  assert.deepEqual(synthesizeManualSpecification(synthesis), expected);
  assert.deepEqual(
    manualFieldErrors(synthesis, [
      { name: "policy.pdf" },
      { name: "notes.txt" },
    ]),
    [],
  );
});

test("each test case selects an existing Persona and Scenario and valid execution settings", () => {
  const invalid: ManualExperiment = {
    id: "Not valid",
    description: " ",
    personas: [
      { id: "same", description: "ok" },
      { id: "same", description: "" },
    ],
    scenarios: [
      { id: "same", description: "" },
      { id: "same", description: "ok" },
    ],
    tasks: [
      {
        ...emptyManualTestCase(),
        num_trials: 21,
        persona_ref: "missing",
        scenario_ref: "missing",
        fixtures: ["missing.pdf"],
      },
    ],
  };
  const fields = manualFieldErrors(invalid, []).map((error) => error.field);
  assert.deepEqual(fields, [
    "experiment.id",
    "experiment.description",
    "persona.1.id",
    "persona.1.description",
    "scenario.0.description",
    "scenario.1.id",
    "scenario.0.tasks",
    "scenario.1.tasks",
    "task.0.persona",
    "task.0.scenario",
    "task.0.trials",
    "task.0.graders",
    "task.0.files",
  ]);
  assert.deepEqual(
    manualFieldErrors(emptyManualExperiment(), []).map((error) => error.field),
    [
      "experiment.id",
      "experiment.description",
      "personas",
      "scenarios",
      "tasks",
    ],
  );
});

test("renaming and removing definitions preserve test case identity and other settings", () => {
  const tasks = [{ ...synthesis.tasks[0], id: "TC-stable" }];
  const renamed = replaceTaskReference(
    replaceTaskReference(tasks, "persona_ref", "analyst", "reviewer"),
    "scenario_ref",
    "supported-answer",
    "new-situation",
  );
  assert.deepEqual(renamed[0], {
    ...tasks[0],
    persona_ref: "reviewer",
    scenario_ref: "new-situation",
  });
  assert.equal(
    replaceTaskReference(renamed, "persona_ref", "reviewer", "")[0].persona_ref,
    "",
  );
  assert.equal(
    replaceTaskReference(renamed, "scenario_ref", "new-situation", "")[0]
      .scenario_ref,
    "",
  );
  assert.equal(
    replaceTaskReference(renamed, "persona_ref", "", "new-person")[0]
      .persona_ref,
    "reviewer",
  );
});

test("keeps fixture bytes until the last test case that uses them is removed", () => {
  const files = ["policy.pdf", "notes.txt", "unused.csv"].map((name) => ({
    name,
    size: 1,
    blob: new Blob(["x"]),
  }));
  assert.deepEqual(
    keepReferencedFixtures(synthesis.tasks.slice(1), files).map((f) => f.name),
    ["policy.pdf", "notes.txt"],
  );
  assert.deepEqual(
    keepReferencedFixtures(synthesis.tasks.slice(2), files).map((f) => f.name),
    ["notes.txt"],
  );
});

test("the same Persona and Scenario can have separate test cases and grader settings", () => {
  const experiment: ManualExperiment = structuredClone(synthesis);
  const [first, second] = experiment.tasks;
  first.id = "TC-first";
  second.id = "TC-second";
  second.persona_ref = first.persona_ref;
  first.graders[1].values = { max_traces: "4" };
  second.graders[1].values = { max_traces: "10" };
  const specification = synthesizeManualSpecification(experiment);
  assert.deepEqual(
    specification.tasks.slice(0, 2).map((t) => t.id),
    ["TC-first", "TC-second"],
  );
  assert.equal(specification.tasks.length, 3);
  assert.equal(
    specification.tasks.reduce((total, t) => total + t.num_trials, 0),
    5,
  );
  const [one, two] = specification.features[0].behaviours;
  assert.deepEqual(one.criteria[1].grader_args, { max_traces: 4 });
  assert.deepEqual(two.criteria[1].grader_args, { max_traces: 10 });
  assert.notDeepEqual(
    specification.tasks[0].behaviour_refs,
    specification.tasks[1].behaviour_refs,
  );
});

const relevanceGrader: GraderSpec = {
  fqn: "metis.library.graders.RelevanceGrader",
  name: "Relevance",
  description: "Whether the replies address what the user needs.",
  uses_criterion_description: false,
  settings: [
    { name: "ground_truth", kind: "list", required: true, base: false },
    {
      name: "turn",
      kind: "choice",
      required: false,
      default: "last",
      choices: ["each", "last"],
      base: false,
    },
    { name: "purpose", kind: "text", required: false, base: false },
    {
      name: "threshold",
      kind: "number",
      required: false,
      default: 0.5,
      base: true,
    },
    {
      name: "scope",
      kind: "choice",
      required: false,
      default: null,
      choices: ["session"],
      base: true,
    },
  ],
};

test("a selected grader starts with its description and the default of each setting", () => {
  const task = selectGrader(emptyManualTestCase(), relevanceGrader);
  assert.deepEqual(task.graders, [
    {
      spec: relevanceGrader,
      description: "Whether the replies address what the user needs.",
      values: {
        ground_truth: "",
        turn: "last",
        purpose: "",
        threshold: "0.5",
        scope: "",
      },
    },
  ]);
  assert.equal(selectGrader(task, relevanceGrader), task);
  assert.deepEqual(deselectGrader(task, relevanceGrader.fqn).graders, []);
});

test("grader settings become the Criterion description and grader args of each setting kind", () => {
  const experiment: ManualExperiment = structuredClone(synthesis);
  let task = selectGrader(
    { ...experiment.tasks[2], graders: [] },
    relevanceGrader,
  );
  task = updateGrader(task, relevanceGrader.fqn, {
    description: "  Replies answer the policy question.  ",
    values: {
      ground_truth: '["Rates rose in 2024."]',
      turn: "each",
      purpose: "true",
      threshold: "0.7",
      scope: "",
    },
  });
  experiment.tasks[2] = task;
  const [criterion] =
    synthesizeManualSpecification(experiment).features[0].behaviours[2]
      .criteria;
  assert.equal(criterion.description, "Replies answer the policy question.");
  assert.deepEqual(criterion.grader_args, {
    ground_truth: ["Rates rose in 2024."],
    turn: "each",
    purpose: "true",
    threshold: 0.7,
  });
});

test("a grader setting that is not valid JSON goes to compile as typed", () => {
  const experiment: ManualExperiment = structuredClone(synthesis);
  experiment.tasks[0] = updateGrader(experiment.tasks[0], budgetGrader.fqn, {
    values: { max_traces: "four" },
  });
  const [, criterion] =
    synthesizeManualSpecification(experiment).features[0].behaviours[0]
      .criteria;
  assert.deepEqual(criterion.grader_args, { max_traces: "four" });
});

test("a grader needs a description and a value for each required setting", () => {
  const experiment: ManualExperiment = structuredClone(synthesis);
  experiment.tasks[0] = selectGrader(experiment.tasks[0], relevanceGrader);
  experiment.tasks[0] = updateGrader(experiment.tasks[0], budgetGrader.fqn, {
    description: " ",
  });
  assert.deepEqual(
    manualFieldErrors(experiment, []).filter((error) =>
      error.field.startsWith("task.0.settings."),
    ),
    [
      {
        field: `task.0.settings.${budgetGrader.fqn}.description`,
        message: "Enter a description.",
      },
      {
        field: `task.0.settings.${relevanceGrader.fqn}.values.ground_truth`,
        message: "Enter a value.",
      },
    ],
  );
});

test("manual task execution settings survive specification construction", () => {
  const experiment: ManualExperiment = structuredClone(synthesis);
  Object.assign(experiment.tasks[0], {
    max_turns: 7,
    timeout_minutes: 2,
    response_wait_ms: 45000,
    max_run_retries: 0,
  });
  const task = synthesizeManualSpecification(experiment).tasks[0];
  assert.equal(task.max_turns, 7);
  assert.equal(task.timeout_minutes, 2);
  assert.equal(task.response_wait_ms, 45000);
  assert.equal(task.max_run_retries, 0);
});

test("manual metadata preserves text and requires unique nonblank keys", () => {
  const experiment: ManualExperiment = structuredClone(synthesis);
  for (const kind of ["personas", "scenarios"] as const) {
    const item = experiment[kind][0];
    item.metadata = [
      { key: "custom context", value: "  exact text  " },
      { key: "count", value: "001" },
      { key: "optional", value: "" },
    ];
    assert.deepEqual(
      synthesizeManualSpecification(experiment)[kind][0].metadata,
      {
        "custom context": "  exact text  ",
        count: "001",
        optional: "",
      },
    );
    const prefix = kind === "personas" ? "persona" : "scenario";
    item.metadata.push({ key: "count", value: "2" }, { key: " ", value: "x" });
    assert.deepEqual(
      manualFieldErrors(experiment, []).filter((error) =>
        error.field.startsWith(`${prefix}.0.metadata`),
      ),
      [
        { field: `${prefix}.0.metadata.3.key`, message: "Use a unique key." },
        { field: `${prefix}.0.metadata.4.key`, message: "Enter a key." },
      ],
    );
    assert.throws(
      () => synthesizeManualSpecification(experiment),
      /unique key/,
    );
    item.metadata = [];
    assert.equal(
      synthesizeManualSpecification(experiment)[kind][0].metadata,
      undefined,
    );
  }
});

test("manual graders can run without an interview criterion", async () => {
  const { manualGraders } = await import("./manual.ts");
  const fallback = {
    fqn: "metis.library.graders.CriterionJudgeGrader",
    name: "Criterion judge",
    description: "Assess an interview criterion.",
    uses_criterion_description: true,
  };
  const budget = {
    fqn: "metis.library.graders.TraceBudgetGrader",
    name: "Trace budget",
    description: "Check the trace count.",
    uses_criterion_description: false,
  };
  assert.deepEqual(manualGraders([fallback, budget]), [budget]);
});

type Taxonomy = NonNullable<GraderSpec["taxonomy"]>;

function taxonomyGrader(
  name: string,
  dimension: GraderSpec["dimension"],
  measure: Taxonomy["measure"],
  scopes: Taxonomy["scopes"],
  grader_types: Taxonomy["grader_types"] = ["llm"],
): GraderSpec {
  return {
    fqn: `metis.library.graders.${name.replaceAll(" ", "")}Grader`,
    name,
    description: `Checks ${name.toLowerCase()}.`,
    uses_criterion_description: false,
    dimension,
    taxonomy: {
      measure,
      scopes,
      grader_types,
      reference_types: ["rubric_based"],
      judgment_forms: ["binary"],
      aggregations: ["none_single_score"],
    },
  };
}

const relevance = taxonomyGrader(
  "Relevance",
  "interaction_quality",
  "relevance",
  ["trace"],
);
const recovery = taxonomyGrader(
  "Error recovery",
  "execution_and_decision_quality",
  "error_recovery",
  ["session"],
);
const success = taxonomyGrader(
  "Task success",
  "task_and_output_quality",
  "task_success",
  ["session"],
  ["llm", "deterministic"],
);
const unclassified = {
  fqn: "metis.library.graders.TraceBudgetGrader",
  name: "Trace budget",
  description: "Check the trace count.",
  uses_criterion_description: false,
};

test("graders are grouped by dimension in taxonomy order with unclassified graders last", () => {
  const groups = graderGroups([unclassified, relevance, recovery, success], "");
  assert.deepEqual(
    groups.map((group) => [group.label, group.graders.map((g) => g.name)]),
    [
      ["Task and Output Quality", ["Task success"]],
      ["Execution and Decision Quality", ["Error recovery"]],
      ["Interaction Quality", ["Relevance"]],
      ["Other", ["Trace budget"]],
    ],
  );
});

test("grader search matches the dimension, measure, and each taxonomy chip", () => {
  const all = [unclassified, relevance, recovery, success];
  const names = (query: string) =>
    graderGroups(all, query).flatMap((group) =>
      group.graders.map((grader) => grader.name),
    );
  assert.deepEqual(names("interaction quality"), ["Relevance"]);
  assert.deepEqual(names("error_recovery"), ["Error recovery"]);
  assert.deepEqual(names("Error recovery"), ["Error recovery"]);
  assert.deepEqual(names("DETERMINISTIC"), ["Task success"]);
  assert.deepEqual(names("trace"), ["Relevance", "Trace budget"]);
  assert.deepEqual(names("rubric based"), [
    "Task success",
    "Error recovery",
    "Relevance",
  ]);
  assert.deepEqual(names("binary"), [
    "Task success",
    "Error recovery",
    "Relevance",
  ]);
  assert.deepEqual(names("no such grader"), []);
});
