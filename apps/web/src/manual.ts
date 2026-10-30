import type {
  Dimension,
  GraderSetting,
  GraderSpec,
  Specification,
} from "./transport/api";

export interface ManualMetadataEntry {
  key: string;
  value: string;
}

export interface ManualPersona {
  metadata?: ManualMetadataEntry[];
  id: string;
  description: string;
}

export interface ManualScenario {
  metadata?: ManualMetadataEntry[];
  id: string;
  description: string;
}

export interface ManualTestCase {
  id: string;

  scenario_ref: string;
  persona_ref: string;
  num_trials: number;
  max_turns?: number;
  timeout_minutes?: number;
  response_wait_ms?: number;
  max_run_retries?: number | null;
  graders: ManualGrader[];
  fixtures: string[];
}

/** One selected grader and the Criterion settings that the test case gives it. */
export interface ManualGrader {
  spec: GraderSpec;
  description: string;
  /** The text that the user typed for each setting, by setting name. Empty means the default. */
  values: Record<string, string>;
}

export interface ManualExperiment {
  id: string;
  description: string;
  personas: ManualPersona[];
  scenarios: ManualScenario[];
  tasks: ManualTestCase[];
}

export interface ManualFixture {
  name: string;
  size: number;
  blob: Blob;
}

export function emptyManualExperiment(): ManualExperiment {
  return {
    id: "",
    description: "",
    personas: [],
    scenarios: [],
    tasks: [],
  };
}

export function emptyManualPersona(): ManualPersona {
  return { id: "", description: "" };
}

export function emptyManualScenario(): ManualScenario {
  return { id: "", description: "" };
}

export function emptyManualTestCase(): ManualTestCase {
  return {
    id: "",

    scenario_ref: "",
    persona_ref: "",
    num_trials: 1,
    graders: [],
    fixtures: [],
  };
}

function settingText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** A new selection starts with the grader's description and the default of each setting. */
export function selectGrader(
  task: ManualTestCase,
  grader: GraderSpec,
): ManualTestCase {
  if (task.graders.some((selected) => selected.spec.fqn === grader.fqn))
    return task;
  const values = Object.fromEntries(
    (grader.settings ?? []).map((setting) => [
      setting.name,
      settingText(setting.default),
    ]),
  );
  return {
    ...task,
    graders: [
      ...task.graders,
      { spec: grader, description: grader.description, values },
    ],
  };
}

export function deselectGrader(
  task: ManualTestCase,
  fqn: string,
): ManualTestCase {
  return {
    ...task,
    graders: task.graders.filter((grader) => grader.spec.fqn !== fqn),
  };
}

export function updateGrader(
  task: ManualTestCase,
  fqn: string,
  patch: Partial<Pick<ManualGrader, "description" | "values">>,
): ManualTestCase {
  return {
    ...task,
    graders: task.graders.map((grader) =>
      grader.spec.fqn === fqn ? { ...grader, ...patch } : grader,
    ),
  };
}

// CHOICE and TEXT values are text. The other kinds are typed as JSON, such as 0.7, true, or ["a"].
const TEXT_KINDS: ReadonlySet<GraderSetting["kind"]> = new Set([
  "choice",
  "text",
]);

function settingValue(setting: GraderSetting, text: string): unknown {
  if (TEXT_KINDS.has(setting.kind)) return text;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    // compile reports the setting that is not valid
    return text;
  }
}

// An empty value is omitted, so the grader uses its default.
function graderArgs(grader: ManualGrader): Record<string, unknown> {
  return Object.fromEntries(
    (grader.spec.settings ?? []).flatMap((setting) => {
      const text = grader.values[setting.name] ?? "";
      return text.trim() === ""
        ? []
        : [[setting.name, settingValue(setting, text)]];
    }),
  );
}

function metadataKeyError(
  entries: readonly ManualMetadataEntry[],
  index: number,
): string | undefined {
  const key = entries[index].key;
  if (!key.trim()) return "Enter a key.";
  if (entries.slice(0, index).some((entry) => entry.key === key))
    return "Use a unique key.";
  return undefined;
}

function metadataFields(entries: readonly ManualMetadataEntry[] = []): {
  metadata?: Record<string, string>;
} {
  if (!entries.length) return {};
  entries.forEach((_, index) => {
    const error = metadataKeyError(entries, index);
    if (error) throw new Error(error);
  });
  return {
    metadata: Object.fromEntries(entries.map(({ key, value }) => [key, value])),
  };
}

export function synthesizeManualSpecification(
  experiment: ManualExperiment,
): Specification {
  const description = experiment.description.trim();
  const behaviours = experiment.tasks.map((task, taskIndex) => {
    const scenario = experiment.scenarios.find(
      (s) => s.id.trim() === task.scenario_ref,
    );
    const label = `${task.scenario_ref}: ${task.persona_ref}`;
    return {
      id: `EB-${taskIndex + 1}`,
      name: label,
      description: scenario?.description.trim() ?? "",
      measured: true,
      criteria: task.graders.map((grader, graderIndex) => ({
        id: `AC-${taskIndex + 1}-${graderIndex + 1}`,
        name: grader.spec.name,
        description: grader.description.trim(),
        grader_fqn: grader.spec.fqn,
        grader_args: graderArgs(grader),
      })),
    };
  });

  return {
    schema_version: 1,
    id: experiment.id.trim(),
    runner_factory_ref:
      "metis.engine.simulation.runners.http.HttpRunnerFactory",
    target: {
      name: experiment.id.trim(),
      description,
      users: "The personas defined in this manual experiment.",
      detail: "",
    },
    features: [
      {
        id: "EP-1",
        name: "Manual experiment",
        description,
        behaviours,
      },
    ],
    personas: experiment.personas.map((persona) => {
      const id = persona.id.trim();
      return {
        id,
        name: id,
        description: persona.description.trim(),
        ...metadataFields(persona.metadata),
      };
    }),
    tasks: experiment.tasks.map((task, index) => ({
      id: task.id,

      scenario_ref: task.scenario_ref,
      persona_ref: task.persona_ref,
      fixtures: [...task.fixtures],
      num_trials: task.num_trials,
      max_turns: task.max_turns ?? 20,
      timeout_minutes: task.timeout_minutes ?? 15,
      response_wait_ms: task.response_wait_ms ?? 300000,
      max_run_retries: task.max_run_retries ?? null,
      behaviour_refs: [behaviours[index].id],
    })),
    scenarios: experiment.scenarios.map((scenario) => {
      const id = scenario.id.trim();
      return {
        id,
        name: id,
        description: scenario.description.trim(),
        ...metadataFields(scenario.metadata),
      };
    }),
  };
}

/**
 * One incomplete field in the manual form. `field` names the control that shows the
 * message: `experiment.id`, `persona.0.description`, `task.1.graders`, and so on.
 * Collection keys (`personas`, `scenarios`, `tasks`) mark an empty collection.
 */
export interface ManualFieldError {
  field: string;
  message: string;
}

function definitionErrors(
  kind: "persona" | "scenario",
  label: string,
  items: readonly (ManualPersona | ManualScenario)[],
): ManualFieldError[] {
  const errors: ManualFieldError[] = [];
  const ids = items.map((item) => item.id.trim());
  items.forEach((item, index) => {
    const entries = item.metadata ?? [];
    entries.forEach((_, row) => {
      const message = metadataKeyError(entries, row);
      if (message)
        errors.push({ field: `${kind}.${index}.metadata.${row}.key`, message });
    });
    const id = ids[index];
    if (!id)
      errors.push({ field: `${kind}.${index}.id`, message: "Enter an ID." });
    else if (ids.indexOf(id) !== index)
      errors.push({
        field: `${kind}.${index}.id`,
        message: `Use an ID that no other ${label} uses.`,
      });
    if (!item.description.trim())
      errors.push({
        field: `${kind}.${index}.description`,
        message: "Enter a description.",
      });
  });
  return errors;
}

export function manualFieldErrors(
  experiment: ManualExperiment,
  fixtures: readonly Pick<ManualFixture, "name">[],
): ManualFieldError[] {
  const errors: ManualFieldError[] = [];
  const add = (field: string, message: string) =>
    errors.push({ field, message });

  const experimentId = experiment.id.trim();
  if (!experimentId) add("experiment.id", "Enter an ID.");
  else if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(experimentId))
    add(
      "experiment.id",
      "Use lowercase words joined by hyphens, such as research-assistant.",
    );
  if (!experiment.description.trim())
    add("experiment.description", "Enter a description.");

  if (!experiment.personas.length) add("personas", "Add at least one Persona.");
  errors.push(...definitionErrors("persona", "Persona", experiment.personas));

  if (!experiment.scenarios.length)
    add("scenarios", "Add at least one Scenario.");
  errors.push(
    ...definitionErrors("scenario", "Scenario", experiment.scenarios),
  );
  experiment.scenarios.forEach((scenario, index) => {
    const id = scenario.id.trim();
    if (id && !experiment.tasks.some((task) => task.scenario_ref === id))
      add(
        `scenario.${index}.tasks`,
        "Select this Scenario in at least one test case.",
      );
  });

  if (!experiment.tasks.length) add("tasks", "Add at least one test case.");
  const scenarioIds = new Set(
    experiment.scenarios.map((s) => s.id.trim()).filter(Boolean),
  );
  const personaIds = new Set(
    experiment.personas.map((p) => p.id.trim()).filter(Boolean),
  );
  const present = new Set(fixtures.map((fixture) => fixture.name));
  experiment.tasks.forEach((task, index) => {
    if (!personaIds.has(task.persona_ref))
      add(`task.${index}.persona`, "Select a Persona.");
    if (!scenarioIds.has(task.scenario_ref))
      add(`task.${index}.scenario`, "Select a Scenario.");
    if (
      !Number.isInteger(task.num_trials) ||
      task.num_trials < 1 ||
      task.num_trials > 20
    )
      add(`task.${index}.trials`, "Enter 1 to 20 Trials.");
    if (!task.graders.length)
      add(`task.${index}.graders`, "Select at least one grader.");
    for (const grader of task.graders) {
      const prefix = `task.${index}.settings.${grader.spec.fqn}`;
      if (!grader.description.trim())
        add(`${prefix}.description`, "Enter a description.");
      for (const setting of grader.spec.settings ?? []) {
        if (setting.required && !(grader.values[setting.name] ?? "").trim())
          add(`${prefix}.values.${setting.name}`, "Enter a value.");
      }
    }
    const missing = task.fixtures.filter((name) => !present.has(name));
    if (missing.length)
      add(`task.${index}.files`, `Choose ${missing.join(", ")} again.`);
  });
  return errors;
}

export function replaceTaskReference(
  tasks: readonly ManualTestCase[],
  field: "persona_ref" | "scenario_ref",
  previousId: string,
  nextId: string,
): ManualTestCase[] {
  const previous = previousId.trim();
  if (!previous) return [...tasks];
  return tasks.map((task) =>
    task[field] === previous ? { ...task, [field]: nextId.trim() } : task,
  );
}

export function referencedFixtureNames(
  tasks: readonly ManualTestCase[],
): string[] {
  return [...new Set(tasks.flatMap((task) => task.fixtures))];
}

export function keepReferencedFixtures(
  tasks: readonly ManualTestCase[],
  fixtures: readonly ManualFixture[],
): ManualFixture[] {
  const referenced = new Set(referencedFixtureNames(tasks));
  return fixtures.filter((fixture) => referenced.has(fixture.name));
}

export function manualGraders(graders: GraderSpec[]): GraderSpec[] {
  // The manual form has no criterion description to give these graders their instructions.
  return graders.filter((grader) => !grader.uses_criterion_description);
}

// Display order of the grader groups. The Record type makes a new Dimension fail typecheck.
export const DIMENSION_LABELS: Record<Dimension, string> = {
  task_and_output_quality: "Task and Output Quality",
  execution_and_decision_quality: "Execution and Decision Quality",
  resource_use: "Resource Use",
  reliability_and_robustness: "Reliability and Robustness",
  safety: "Safety",
  security: "Security",
  interaction_quality: "Interaction Quality",
};

// Words that sentence case would spell wrongly.
const TAXONOMY_WORDS: Record<string, string> = { llm: "LLM" };

/** `tool_argument_correctness` → `Tool argument correctness`, `llm` → `LLM`. */
export function taxonomyLabel(value: string): string {
  const words = value.split("_").map((word) => TAXONOMY_WORDS[word] ?? word);
  const [first = "", ...rest] = words;
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(" ");
}

export interface GraderGroup {
  dimension: Dimension | null;
  label: string;
  graders: GraderSpec[];
}

function graderSearchText(grader: GraderSpec): string {
  const taxonomy = grader.taxonomy;
  const values = [
    ...(taxonomy?.measure ? [taxonomy.measure] : []),
    ...(taxonomy?.grader_types ?? []),
    ...(taxonomy?.scopes ?? []),
    ...(taxonomy?.reference_types ?? []),
    ...(taxonomy?.judgment_forms ?? []),
  ];
  return [
    grader.name,
    grader.description,
    grader.dimension ? DIMENSION_LABELS[grader.dimension] : "",
    ...values,
    ...values.map(taxonomyLabel),
  ]
    .join("\n")
    .toLowerCase();
}

/** The graders that match the query, grouped by Dimension in display order. */
export function graderGroups(
  graders: GraderSpec[],
  query: string,
): GraderGroup[] {
  const value = query.trim().toLowerCase();
  const shown = value
    ? graders.filter((grader) => graderSearchText(grader).includes(value))
    : graders;
  const groups: GraderGroup[] = [
    ...(Object.keys(DIMENSION_LABELS) as Dimension[]).map((dimension) => ({
      dimension,
      label: DIMENSION_LABELS[dimension],
      graders: shown.filter((grader) => grader.dimension === dimension),
    })),
    {
      dimension: null,
      label: "Other",
      graders: shown.filter((grader) => !grader.dimension),
    },
  ];
  return groups.filter((group) => group.graders.length > 0);
}
