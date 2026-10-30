import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { Specification } from "./transport/api";
import { ActiveReview, Composer, Transcript } from "./Conversation";
import { Done } from "./Done";
import { PairsInput, parsePairs } from "./fields";
import { SpecificationView } from "./SpecificationView";

function specification(
  target: Partial<Specification["target"]> = {},
): Specification {
  return {
    schema_version: 1,
    id: "test",
    runner_factory_ref:
      "metis.engine.simulation.runners.http.HttpRunnerFactory",
    tasks: [],
    target: {
      name: "",
      users: "",
      description: "",
      detail: "",
      ...target,
    },
    features: [],
    personas: [],
    scenarios: [],
  };
}

function render(
  value: Specification,
  state: { busy?: boolean; interviewStep?: string } = {},
): string {
  return renderToStaticMarkup(
    <SpecificationView
      specification={value}
      interviewStep={state.interviewStep}
      busy={state.busy}
      showGraders={false}
      onShowGradersChange={() => undefined}
      graderByFqn={new Map()}
      gradersLoading={false}
      gradersError={false}
    />,
  );
}

function section(markup: string, title: string, nextTitle: string): string {
  const heading = (name: string) =>
    markup.search(new RegExp(`<h2 [^>]*>(?:<[^>]+>)*${name}<`));
  const start = heading(title);
  const end = heading(nextTitle);
  assert.notEqual(start, -1, `${title} heading is present`);
  assert.notEqual(end, -1, `${nextTitle} heading is present`);
  return markup.slice(start, end);
}

function occurrences(value: string, part: string): number {
  return value.split(part).length - 1;
}

test("the empty document scaffolds all four Target fields", () => {
  const markup = render(specification());
  const target = section(markup, "Target", "Features / Expected Behaviours");

  assert.match(target, />Name<\/h3>/);
  assert.match(target, />Description<\/h3>/);
  assert.match(target, />Users<\/h3>/);
  assert.match(target, />Details<\/h3>/);
  assert.equal(occurrences(target, "placeholder-rule"), 12);
});

test("each written Target value replaces only its own placeholder", () => {
  const markup = render(specification({ users: "policy analysts" }));
  const target = section(markup, "Target", "Features / Expected Behaviours");

  assert.match(target, /policy analysts/);
  assert.equal(occurrences(target, "placeholder-rule"), 9);
});

test("resumed values are complete and preserve paragraphs and line lists", () => {
  const markup = render(
    specification({
      name: "Research assistant",
      description: "Answers research questions.",
      users: "People\n- policy analysts\n- reviewers",
      detail: "Searches the library.\nReturns cited answers.",
    }),
  );
  const target = section(markup, "Target", "Features / Expected Behaviours");

  assert.match(target, /People\n- policy analysts\n- reviewers/);
  assert.match(target, /Searches the library\.\nReturns cited answers\./);
  assert.equal(occurrences(target, "placeholder-rule"), 0);
});

test("clarify marks only Target and leaves its document content read-only", () => {
  const markup = render(specification(), {
    busy: true,
    interviewStep: "clarify",
  });
  const target = section(markup, "Target", "Features / Expected Behaviours");

  assert.equal(occurrences(markup, "is-writing"), 1);
  assert.equal(occurrences(markup, "section-writing-marker"), 1);
  assert.doesNotMatch(target, /<(?:input|textarea|button)\b/);
});

test("the document keeps node names and descriptions in their presentation roles", () => {
  const value: Specification = {
    ...specification({
      name: "Research assistant",
      description: "Answers questions.",
    }),
    features: [
      {
        id: "F-1",
        name: "Answer quality",
        description: "Answer accurately and cite useful evidence.",
        behaviours: [
          {
            id: "EB-1",
            name: "Cite sources",
            description: "Cites every factual claim.",
            measured: true,
            criteria: [
              {
                id: "AC-1-1",
                name: "Supported answer",
                grader_fqn: "metis.graders.answer_quality",
                description:
                  "Given a question, when the answer returns, then each claim cites its source.",
              },
            ],
          },
        ],
      },
    ],
    personas: [
      {
        id: "careful-reviewer",
        name: "Careful reviewer",
        description: "Checks outputs.",
      },
    ],
    tasks: [
      {
        id: "TC-001",

        scenario_ref: "S-1",
        persona_ref: "careful-reviewer",
        fixtures: [],
        num_trials: 3,
        max_turns: 20,
        timeout_minutes: 15,
        response_wait_ms: 300000,
        max_run_retries: null,
        behaviour_refs: ["EB-1"],
      },
    ],
    scenarios: [
      {
        id: "S-1",
        name: "Supported question",
        description: "Ask a question the library covers.",
      },
    ],
  };
  const markup = render(value);

  assert.match(markup, /Answer quality/);
  assert.match(markup, /Answer accurately and cite useful evidence\./);
  assert.match(markup, /Cite sources/);
  assert.match(markup, /Cites every factual claim\./);
  assert.match(markup, /Supported answer/);
  assert.match(markup, /the answer returns/);
  assert.match(markup, /each claim cites its source/);
  assert.match(markup, /Careful reviewer/);
  assert.match(markup, /Checks outputs\./);
  assert.match(markup, /Supported question/);
  assert.match(markup, /Ask a question the library covers\./);
  assert.doesNotMatch(markup, />analyst<\/span>/);
});

test("hides grader identifiers and shows only the human summary when enabled", () => {
  const value = specification();
  value.features = [
    {
      id: "F-1",
      name: "Answer quality",
      description: "Answer accurately.",
      behaviours: [
        {
          id: "EB-1",
          name: "Cite sources",
          description: "Cites claims.",
          measured: true,
          criteria: [
            {
              id: "AC-1-1",
              name: "Supported answer",
              grader_fqn: "metis.graders.answer_quality",
              description:
                "Given a question, when it answers, then claims cite sources.",
            },
          ],
        },
      ],
    },
  ];
  const hidden = render(value);
  assert.doesNotMatch(hidden, /Answer quality grader/);
  const visible = renderToStaticMarkup(
    <SpecificationView
      specification={value}
      showGraders
      onShowGradersChange={() => undefined}
      graderByFqn={
        new Map([
          [
            "metis.graders.answer_quality",
            {
              fqn: "metis.graders.answer_quality",
              name: "Answer quality grader",
              description: "Checks supported answers.",
              uses_criterion_description: false,
            },
          ],
        ])
      }
      gradersLoading={false}
      gradersError={false}
    />,
  );
  assert.match(visible, /Answer quality grader/);
  assert.doesNotMatch(visible, /metis\.graders\.answer_quality/);
});

test("the generic form renderer transports names, descriptions, and opaque targets", () => {
  const markup = renderToStaticMarkup(
    <Transcript
      requests={[
        {
          type: "form",
          cancellable: false,
          prompt: "Add a Behaviour",
          state: "pending",
          fields: [
            {
              id: "name",
              label: "Name",
              placeholder: "",
              multiline: false,
              input_type: "string" as const,
              value: "",
              required: false,
              choices: [],
              help: "",
            },
            {
              id: "description",
              label: "Description",
              placeholder: "",
              multiline: true,
              input_type: "string" as const,
              value: "",
              required: false,
              choices: [],
              help: "",
            },
          ],
          target: "F-2",
          answer: {},
          request_id: "form-1",
          stage: "behaviours",
        },
      ]}
      busy={false}
      onRespond={() => undefined}
    />,
  );

  assert.match(markup, /Add a Behaviour/);
  assert.match(markup, />Name<\/span>/);
  assert.match(markup, />Description<\/span>/);
  assert.match(markup, /<textarea/);
  assert.match(markup, /<input/);
  assert.doesNotMatch(markup, /F-2/);
});

test("wizard upload fields render a working local file control", () => {
  const markup = renderToStaticMarkup(
    <Transcript
      requests={[
        {
          type: "choice",
          prompt: "Add scenario files",
          title: "Scenarios",
          step: 5,
          steps: 5,
          state: "pending",
          request_id: "choice-upload",
          stage: "scenarios",
          options: [],
          multi: false,
          cards: [
            {
              kind: "scenario",
              id: "S-1",
              title: "Support case",
              section: "Scenarios",
              selected: null,
              components: [
                {
                  type: "upload",
                  id: { action: "files", target: "S-1" },
                  label: "Files",
                  value: ["policy.pdf"],
                },
              ],
              options: [],
              note: null,
              blocking: false,
              trials: 1,
            },
          ],
          warnings: [],
          footer: null,
          instruction: null,
        },
      ]}
      busy={false}
      onRespond={() => undefined}
    />,
  );

  assert.match(markup, /type="file"/);
  assert.match(markup, /policy\.pdf/);
  assert.doesNotMatch(markup, /File attachments are not available/);
});

test("the docked composer fills the conversation column", () => {
  const markup = renderToStaticMarkup(
    <Composer
      request={{
        type: "chat",
        prompt: "What should change?",
        title: "Scenarios",
        step: 5,
        steps: 5,
        state: "pending",
        request_id: "chat-1",
        stage: "scenarios",
        multiline: true,
        answer: "",
      }}
      busy={false}
      onSend={() => undefined}
    />,
  );

  assert.match(markup, /class="w-full pb-6 pt-2"/);
});

test("the Specification output action follows Interview completion", () => {
  const shared = {
    specification: specification(),
    showGraders: false,
    onShowGradersChange: () => undefined,
    graderByFqn: new Map(),
    gradersLoading: false,
    gradersError: false,
    onFinish: () => undefined,
    onDownload: () => undefined,
  };
  const pending = renderToStaticMarkup(<SpecificationView {...shared} />);
  const complete = renderToStaticMarkup(<SpecificationView {...shared} done />);

  assert.match(pending, /Skip interview and download specification/);
  assert.doesNotMatch(pending, />Download specification</);
  assert.match(complete, />Download specification</);
  assert.doesNotMatch(complete, /Skip interview/);
});

test("a completed Interview reports that its specification is ready", () => {
  const markup = renderToStaticMarkup(<Done />);

  assert.match(markup, /Your specification is ready/);
  assert.doesNotMatch(markup, /Your evaluation is ready/);
});

test("an inline edit keeps the checkbox and id and draws the form in the card's place", () => {
  const card = {
    kind: "standard" as const,
    id: "item-1",
    blocking: false,
    title: "Cite sources",
    section_id: "group-1",
    section: "Research",
    selected: true,
    components: [{ type: "text" as const, text: "Include evidence." }],
    options: [
      {
        id: { action: "tick", target: "item-1" },
        label: "Select",
        primary: false,
        selected: true,
        enabled: true,
      },
      {
        id: { action: "edit", target: "item-1" },
        label: "Edit",
        primary: false,
        enabled: true,
        icon: "pencil" as const,
      },
    ],
  };
  const field = {
    placeholder: "",
    input_type: "string" as const,
    required: false,
    help: "",
  };
  const markup = renderToStaticMarkup(
    <ActiveReview
      request={{
        type: "choice",
        prompt: "Select",
        title: "Review",
        stage: "behaviours",
        request_id: "review-1",
        state: "resolved",
        warnings: [],
        multi: true,
        options: [],
        cards: [card],
      }}
      form={{
        type: "form",
        prompt: "Edit Cite sources.",
        state: "pending",
        request_id: "edit",
        stage: "behaviours",
        purpose: "edit",
        cancellable: true,
        target: "item-1",
        answer: {},
        fields: [
          {
            ...field,
            id: "name",
            label: "Name",
            value: "Cite sources",
            multiline: false,
          },
          {
            ...field,
            id: "description",
            label: "Description",
            value: "Include evidence.",
            multiline: true,
          },
          {
            ...field,
            id: "limit",
            label: "Maximum traces",
            value: "3",
            input_type: "integer",
            multiline: false,
            group: "Settings",
          },
        ],
      }}
      busy={false}
      onRespond={() => undefined}
    />,
  );
  const form = markup.slice(markup.indexOf("<form"));
  assert.match(form, /type="checkbox"[^>]*checked=""/);
  assert.match(form, /item-1<\/span>/);
  assert.ok(form.indexOf('value="Cite sources"') < form.indexOf("<textarea"));
  assert.match(form, />Save<\/button>/);
  assert.match(form, />Cancel<\/button>/);
  assert.doesNotMatch(form, /aria-label="Edit"/);
  assert.match(form, /aria-expanded="false"[^>]*>.*Settings/);
  assert.match(form, /hidden=""[^>]*>.*value="3"/);
});

test("a card with no tick option draws no checkbox", () => {
  const markup = renderToStaticMarkup(
    <ActiveReview
      request={{
        type: "choice",
        prompt: "Review",
        title: "Personas",
        stage: "personas",
        request_id: "review-2",
        state: "pending",
        warnings: [],
        multi: false,
        options: [],
        cards: [
          {
            kind: "standard",
            id: "P-1",
            blocking: false,
            title: "Careful reviewer",
            selected: true,
            components: [{ type: "text", text: "Checks outputs." }],
            options: [],
          },
        ],
      }}
      busy={false}
      onRespond={() => undefined}
    />,
  );
  assert.match(markup, /Careful reviewer/);
  assert.doesNotMatch(markup, /type="checkbox"/);
});

test("the composer stays open on a review while its edit form waits", () => {
  const review = {
    type: "choice" as const,
    prompt: "Review",
    title: "Behaviours",
    stage: "behaviours" as const,
    request_id: "review-1",
    state: "resolved" as const,
    feedback_placeholder: "Add, change, or select Behaviours",
    warnings: [],
    multi: true,
    options: [],
    cards: [],
  };
  const typing = renderToStaticMarkup(
    <Composer request={review} busy={false} onSend={() => undefined} />,
  );
  assert.match(typing, /placeholder="Add, change, or select Behaviours"/);
  assert.doesNotMatch(typing, /<textarea[^>]*disabled=""/);
  const sending = renderToStaticMarkup(
    <Composer request={review} busy onSend={() => undefined} value="More" />,
  );
  assert.doesNotMatch(sending, /<textarea[^>]*disabled=""/);
  assert.match(sending, /aria-label="Send" disabled=""/);
});

test("grouped review exposes labelled selections and separate Continue", () => {
  const markup = renderToStaticMarkup(
    <ActiveReview
      request={{
        type: "choice",
        prompt: "Select",
        title: "Review",
        stage: "behaviours",
        request_id: "review-1",
        state: "pending",
        warnings: [],
        multi: true,
        instruction: "Select what matters.",
        options: [
          {
            id: { action: "next" },
            label: "Continue",
            primary: true,
            enabled: true,
          },
        ],
        cards: [
          {
            kind: "standard",
            id: "item-1",
            blocking: false,
            title: "Cite sources",
            section_id: "group-1",
            section: "Research",
            selected: true,
            components: [{ type: "text", text: "Include evidence." }],
            options: [
              {
                id: { action: "opaque", target: "item-1" },
                label: "Select",
                primary: false,
                selected: true,
                enabled: true,
              },
            ],
          },
        ],
      }}
      busy={false}
      onRespond={() => {}}
    />,
  );
  // A group heading shows its name only, with no selected count.
  assert.doesNotMatch(markup, /of 1 selected/);
  assert.match(markup, /aria-expanded="true"/);
  assert.match(markup, /for="review-item-1"/);
  assert.match(markup, /Include evidence/);
  assert.match(markup, /Continue/);
  assert.doesNotMatch(markup, /disabled=""/);
});

test("a Test Case row ticks, shows id chips with hints, and edits only after the pencil", () => {
  const cover = (id: string, selected: boolean) => ({
    id: { action: "cover", target: "TC-001", via: id },
    label: id,
    hint: `Description of ${id}`,
    selected,
    primary: false,
    enabled: true,
  });
  const row = {
    kind: "scenario" as const,
    id: "TC-001",
    title: "TC-001",
    blocking: false,
    trials: 3,
    selected: true,
    profile_section_id: "test-cases" as const,
    components: [],
    columns: [
      { title: "Persona", summary: "Careful reviewer", components: [] },
      { title: "Scenario", summary: "Supported question", components: [] },
      {
        title: "Behaviours",
        summary: "EB-1",
        components: [
          { type: "options" as const, options: [cover("EB-1", true)] },
        ],
      },
    ],
    options: [
      {
        id: { action: "tick", target: "TC-001" },
        label: "Include TC-001",
        selected: true,
        primary: false,
        enabled: true,
      },
      {
        id: { action: "edit", target: "TC-001" },
        label: "Edit TC-001",
        icon: "pencil" as const,
        primary: false,
        enabled: true,
      },
    ],
  };
  const review = {
    type: "choice" as const,
    prompt: "Review",
    title: "Test Cases",
    stage: "scenarios" as const,
    request_id: "review-tc",
    state: "pending" as const,
    profile_section_id: "test-cases" as const,
    warnings: [],
    multi: true,
    options: [],
    cards: [row],
  };
  const shown = renderToStaticMarkup(
    <ActiveReview request={review} busy={false} onRespond={() => undefined} />,
  );
  assert.match(shown, /aria-label="Include TC-001"[^>]*checked=""/);
  assert.match(shown, /title="Description of EB-1"/);
  assert.doesNotMatch(shown, /Remove selected/);
  assert.doesNotMatch(shown, /aria-pressed/);

  const field = {
    placeholder: "",
    input_type: "string" as const,
    required: true,
    help: "",
    multiline: false,
  };
  const editing = renderToStaticMarkup(
    <ActiveReview
      request={{ ...review, state: "resolved" }}
      form={{
        type: "form",
        prompt: "Change TC-001.",
        state: "pending",
        request_id: "edit-tc",
        stage: "scenarios",
        purpose: "edit",
        cancellable: true,
        target: "TC-001",
        answer: {},
        fields: [
          {
            ...field,
            id: "persona",
            label: "Persona",
            value: "P-1",
            column: "Persona",
            choices: [{ value: "P-1", label: "Careful reviewer" }],
          },
          {
            ...field,
            id: "behaviours",
            label: "Behaviours",
            value: "EB-1",
            column: "Behaviours",
            multiple: true,
            choices: [
              { value: "EB-1", label: "EB-1", hint: "Cites sources." },
              { value: "EB-2", label: "EB-2", hint: "Stays short." },
            ],
          },
        ],
      }}
      busy={false}
      onRespond={() => undefined}
    />,
  );
  const cells = editing.split("<td");
  const personaCell = cells.findIndex((cell) => cell.includes("<select"));
  const chipsCell = cells.findIndex((cell) => cell.includes('role="group"'));
  assert.ok(personaCell > 0 && chipsCell > personaCell);
  assert.match(
    cells[chipsCell],
    /aria-pressed="true"[^>]*title="Cites sources\."/,
  );
  assert.match(
    cells[chipsCell],
    /aria-pressed="false"[^>]*title="Stays short\."/,
  );
  assert.match(editing, /<select form="row-edit-TC-001"/);
  assert.match(editing, /<form id="row-edit-TC-001"/);
});

test("a card shows its id only when it asks for it", () => {
  const card = (show_id: boolean) => ({
    kind: "standard" as const,
    id: "careful-reviewer",
    title: "Careful reviewer",
    blocking: false,
    show_id,
    components: [],
    options: [],
  });
  const markup = (show_id: boolean) =>
    renderToStaticMarkup(
      <ActiveReview
        request={{
          type: "choice",
          prompt: "Review",
          title: "Personas",
          stage: "personas",
          request_id: "r",
          state: "pending",
          warnings: [],
          multi: false,
          options: [],
          cards: [card(show_id)],
        }}
        busy={false}
        onRespond={() => undefined}
      />,
    );
  assert.doesNotMatch(markup(false), />careful-reviewer</);
  assert.match(markup(true), />careful-reviewer</);
});

test("a details field shows one name and value box per detail, with no separator to type", () => {
  const markup = renderToStaticMarkup(
    <PairsInput
      ariaLabel="More information"
      value={JSON.stringify([["Role", "Policy analyst"]])}
      placeholder="Role|Policy analyst"
      onChange={() => undefined}
    />,
  );
  assert.match(markup, /aria-label="More information 1 name"[^>]*value="Role"/);
  assert.match(
    markup,
    /aria-label="More information 1 value"[^>]*value="Policy analyst"/,
  );
  assert.match(markup, /Add a detail/);
  assert.deepEqual(parsePairs("not json"), []);
});
