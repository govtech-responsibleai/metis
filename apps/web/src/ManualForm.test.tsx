import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  bindingFromDraft,
  emptyConnectionDraft,
  startConnection,
  type ConnectionDraft,
} from "./connection";
import {
  focusManualInput,
  itemHeading,
  ManualForm,
  packageManualExperiment,
  type ManualFormProps,
} from "./ManualForm";
import {
  emptyManualTestCase,
  emptyManualExperiment,
  emptyManualScenario,
  type ManualExperiment,
} from "./manual";
import type { ConnectionCheckResult } from "./transport/api";

const runDraft: ConnectionDraft = {
  ...emptyConnectionDraft(),
  mode: "run",
  name: "Policy assistant",
  specUrl: "${APP_URL}/openapi.json",
  secretEnv: "APP_KEY",
};

const validCheck: ConnectionCheckResult = {
  binding: bindingFromDraft(runDraft) as ConnectionCheckResult["binding"],
  errors: [],
  live: false,
  probes: [],
  status: "unchecked",
};

const invalidCheck: ConnectionCheckResult = {
  binding: null,
  errors: [{ loc: ["spec_url"], msg: "spec_url must not hold a user name" }],
  live: false,
  probes: [],
  status: "unchecked",
};

function props(overrides: Partial<ManualFormProps> = {}): ManualFormProps {
  return {
    onBack: () => undefined,
    connectionDraft: emptyConnectionDraft(),
    onConnectionDraft: () => undefined,
    connectionResult: null,
    onTestConnection: () => undefined,
    checkConnection: async () => validCheck,
    ...overrides,
  };
}

const experiment: ManualExperiment = {
  id: "manual-test",
  description: "A manual experiment.",
  personas: [{ id: "reviewer", description: "A reviewer." }],
  scenarios: [{ id: "check-answer", description: "Check one answer." }],
  tasks: [
    {
      id: "",
      scenario_ref: "check-answer",
      num_trials: 1,
      persona_ref: "reviewer",
      fixtures: [],
      graders: [
        {
          spec: {
            fqn: "metis.library.graders.demo.DemoTraceBudgetGrader",
            name: "Turn budget",
            description: "Checks the turn budget.",
            uses_criterion_description: false,
          },
          description: "Checks the turn budget.",
          values: {},
        },
      ],
    },
  ],
};

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

// Records each request path and the package form, and answers compile and package.
function recordRequests() {
  const paths: string[] = [];
  let form: FormData | undefined;
  globalThis.fetch = async (input, init) => {
    const path = String(input);
    paths.push(path);
    if (path === "/api/v1/wizard/compile") {
      const specification = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          "specification.yaml": "",
          specification: {
            ...specification,
            tasks: specification.tasks.map((task: object) => ({
              ...task,
              id: "T-1",
            })),
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    form = init?.body as FormData;
    return new Response(new Blob(["zip"]), {
      status: 200,
      headers: {
        "Content-Disposition":
          'attachment; filename="20261016-223045-manual.zip"',
      },
    });
  };
  return { paths, form: () => form };
}

test("the new manual form presents its Experiment sections in order", () => {
  const markup = renderToStaticMarkup(<ManualForm {...props()} />);
  assert.match(markup, /Return to the opening screen/);
  assert.match(markup, /aria-label="Experiment ID"/);
  assert.doesNotMatch(markup, />New Persona<\/h4>/);
  assert.doesNotMatch(markup, />New Scenario<\/h4>/);
  assert.match(markup, /aria-label="Add Persona"/);
  assert.match(markup, /aria-label="Add Scenario"/);
  assert.match(markup, /No Personas yet/);
  assert.match(markup, /aria-label="Add test case"/);
  assert.match(markup, />ID<\/span>/);
  assert.match(markup, />Description<\/span>/);
  assert.match(markup, /Download specification/);
  assert.doesNotMatch(markup, /Still needs/);
  assert.doesNotMatch(markup, />Feature</);
  assert.doesNotMatch(markup, />Behaviour</);
  assert.doesNotMatch(markup, />Criterion</);

  const details = markup.indexOf('id="manual-experiment-details"');
  const personas = markup.indexOf('id="manual-personas"');
  const scenarios = markup.indexOf('id="manual-scenarios"');
  assert.ok(details >= 0);
  assert.ok(details < personas);
  assert.ok(personas < scenarios);
  assert.ok(scenarios < markup.indexOf('id="manual-tasks"'));
});

test("new definitions and test cases start with explicit empty selections", () => {
  const experiment = emptyManualExperiment();
  assert.deepEqual(experiment.personas, []);
  assert.deepEqual(experiment.scenarios, []);
  assert.deepEqual(experiment.tasks, []);
  assert.deepEqual(emptyManualScenario(), { id: "", description: "" });
  assert.equal(emptyManualTestCase().persona_ref, "");
  assert.equal(emptyManualTestCase().scenario_ref, "");
});

test("manual item headings describe blank and entered IDs", () => {
  assert.equal(itemHeading("Persona", ""), "New Persona");
  assert.equal(
    itemHeading("Scenario", " supported-answer "),
    "supported-answer",
  );
});

test("manual item addition can focus the new ID control", () => {
  const focused: string[] = [];
  const persona = { focus: () => focused.push("persona") };
  const scenario = { focus: () => focused.push("scenario") };
  const task = { focus: () => focused.push("task") };
  assert.equal(
    focusManualInput({ kind: "task", index: 0 }, [], [], [task]),
    true,
  );

  assert.equal(
    focusManualInput({ kind: "persona", index: 0 }, [persona], []),
    true,
  );
  assert.equal(
    focusManualInput({ kind: "scenario", index: 0 }, [], [scenario]),
    true,
  );
  assert.equal(
    focusManualInput({ kind: "persona", index: 1 }, [persona], []),
    false,
  );
  assert.deepEqual(focused, ["task", "persona", "scenario"]);
});

test("the manual form keeps the mode that the opening chose", () => {
  const spec = renderToStaticMarkup(<ManualForm {...props()} />);
  assert.match(spec, /aria-checked="true"[^>]*>Build Spec only</);
  assert.doesNotMatch(spec, /id="manual-connection"/);

  const run = renderToStaticMarkup(
    <ManualForm {...props({ connectionDraft: runDraft })} />,
  );
  assert.match(run, /aria-checked="true"[^>]*>Build Spec and connect target</);
  assert.match(run, /<h2 id="manual-specification"[^>]*>Specification<\/h2>/);
  assert.match(run, /<h2 id="manual-connection"[^>]*>Target connection<\/h2>/);
  assert.match(run, />Test connection</);
  // The download sits next to the mode picker, above both parts.
  assert.ok(
    run.indexOf("Download specification") <
      run.indexOf('id="manual-specification"'),
  );
  assert.ok(
    run.indexOf('id="manual-specification"') <
      run.indexOf('id="manual-connection"'),
  );
});

test("run mode with an invalid binding marks the card and does not download", async () => {
  const markup = renderToStaticMarkup(
    <ManualForm
      {...props({ connectionDraft: runDraft, connectionResult: invalidCheck })}
    />,
  );
  assert.match(markup, /The target connection is not valid/);

  const requests = recordRequests();
  const archive = await packageManualExperiment(
    experiment,
    [],
    async () => startConnection(runDraft, invalidCheck),
    () => undefined,
  );

  assert.equal(archive, null);
  assert.deepEqual(requests.paths, []);
});

test("run mode with a valid binding sends the connection with the Specification", async () => {
  const requests = recordRequests();
  let taskIds: Array<string | undefined> = [];
  const connection = startConnection(runDraft, validCheck);
  assert.ok(connection);

  const archive = await packageManualExperiment(
    experiment,
    [],
    async () => connection,
    (ids) => {
      taskIds = ids;
    },
  );

  assert.equal(archive?.filename, "20261016-223045-manual.zip");
  assert.deepEqual(requests.paths, [
    "/api/v1/wizard/compile",
    "/api/v1/wizard/package",
  ]);
  assert.deepEqual(
    JSON.parse(String(requests.form()?.get("connection"))),
    connection,
  );
  assert.ok(requests.form()?.get("specification"));
  assert.deepEqual(taskIds, ["T-1"]);
});

test("spec-only mode sends no connection field", async () => {
  const requests = recordRequests();

  await packageManualExperiment(experiment, [], null, () => undefined);

  assert.equal(requests.form()?.has("connection"), false);
  assert.ok(requests.form()?.get("specification"));
});
