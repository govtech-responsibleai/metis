import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type {
  ChoiceRequest,
  FormRequest,
  InterviewDocument,
  InterviewState,
  InterviewSuccess,
  UserResponse,
} from "../transport/api.ts";
import { api } from "../transport/api.ts";
import { downloadArchive } from "../download.ts";
import {
  addFixtures,
  fixturesForSpecification,
  InterviewRepository,
  emptyRecord,
  removeUnreferencedFixtures,
} from "../storage/repository.ts";
import { InterviewOperations } from "./operations.ts";
import {
  applyEnd,
  applyTurn,
  startTranscript,
  toPresentation,
} from "./transcript.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

const baseState = (): InterviewState => ({
  specification: {
    schema_version: 1,
    id: "test",
    runner_factory_ref:
      "metis.engine.simulation.runners.http.HttpRunnerFactory",
    tasks: [],
    target: { name: "", users: "", description: "", detail: "" },
    features: [],
    personas: [],
    scenarios: [],
  },
  behaviours_confirmed: false,
  confirmed: false,
  context: {
    perspective: "end_user",
    opening_description: "",
    capability_evidence: { known_capability_ids: [], confidence: "low" },
  },
  history: [],
  user_typed: [],
  issued_ids: [],
  pending: {
    type: "chat",
    prompt: "What does it do?",
    title: "Clarify",
    step: 1,
    steps: 5,
    state: "pending",
    request_id: "chat-1",
    stage: "clarify",
    multiline: true,
    answer: "",
  },
});

function success(
  state: InterviewState,
  outcome: InterviewSuccess["outcome"],
): InterviewSuccess {
  return {
    type: "success",
    state,
    stage: state.pending?.stage ?? "done",
    missing: [],
    outcome,
  };
}

function choiceRequest(): ChoiceRequest {
  return {
    type: "choice",
    prompt: "Choose a goal",
    title: "Behaviours",
    step: 2,
    steps: 5,
    state: "pending",
    request_id: "choice-1",
    stage: "behaviours",
    options: [
      {
        id: { action: "continue" },
        label: "Continue",
        primary: true,
        enabled: true,
      },
    ],
    multi: false,
    cards: [],
    warnings: [],
    footer: null,
    instruction: null,
  };
}

function formRequest(): FormRequest {
  return {
    type: "form",
    cancellable: false,
    prompt: "Name the behaviour",
    title: "Behaviours",
    step: 2,
    steps: 5,
    state: "pending",
    request_id: "form-1",
    stage: "behaviours",
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
    ],
    target: "B-1",
    answer: {},
  };
}

const policyTask = (fixtures: string[]) => ({
  id: "S-1",

  description: "Ask about one policy rule.",
  scenario_ref: "S-1",
  persona_ref: "P-1",
  behaviour_refs: [],
  fixtures,
  num_trials: 1,
  max_turns: 20,
  timeout_minutes: 15,
  response_wait_ms: 300000,
  max_run_retries: null,
});

test("runs a document interview through skip, review, reload and package", async () => {
  const initialDocuments: InterviewDocument[] = [
    {
      name: "policy.md",
      text: "The policy text.",
    },
    {
      name: "notes.txt",
      text: "Interview notes.",
    },
  ];
  const emptyStartState = baseState();
  const startState: InterviewState = {
    ...emptyStartState,
    context: {
      ...emptyStartState.context,
      opening_description: "A support assistant",
      documents: [...initialDocuments],
    },
  };
  const choice = choiceRequest();
  const draftState: InterviewState = {
    ...startState,
    pending: null,
    confirmed: false,
    specification: {
      ...startState.specification,
      tasks: [policyTask(["policy.md"])],
    },
  };

  const scenarioRequest = (
    request_id: string,
    files: string[],
  ): ChoiceRequest => ({
    ...choice,
    request_id,
    title: "Scenarios",
    stage: "scenarios",
    step: 5,
    sections: [],
    cards: [
      {
        kind: "scenario",
        id: "S-1",
        title: "Check policy",
        blocking: false,
        trials: 1,
        components: [
          {
            type: "upload",
            id: { action: "files", target: "S-1" },
            label: "Files sent to your target",
            value: files,
            available: ["policy.md", "notes.txt"],
          },
        ],
        options: [],
      },
    ],
  });
  const reviewState: InterviewState = {
    ...draftState,
    pending: scenarioRequest("review-1", ["policy.md"]),
  };
  const selectedState: InterviewState = {
    ...reviewState,
    pending: scenarioRequest("review-2", ["notes.txt"]),
    specification: {
      ...reviewState.specification,
      tasks: reviewState.specification.tasks.map((scenario) => ({
        ...scenario,
        fixtures: ["notes.txt"],
      })),
    },
  };
  const finalState: InterviewState = {
    ...selectedState,
    pending: null,
    confirmed: true,
  };

  globalThis.fetch = async (input, init) => {
    const path = String(input);
    if (path.endsWith("/documents/extract"))
      return new Response(
        JSON.stringify({
          documents: [
            { name: "policy.md", text: "The policy text." },
            { name: "notes.txt", text: "Interview notes." },
          ],
        }),
        { status: 200 },
      );
    if (path.endsWith("/start"))
      return new Response(
        JSON.stringify(success(startState, "awaiting_response")),
        { status: 200 },
      );
    if (path.endsWith("/turn")) {
      const body = JSON.parse(String(init?.body)) as { request_id: string };
      assert.ok(["review-1", "review-2"].includes(body.request_id));
      const next = body.request_id === "review-1" ? selectedState : finalState;
      return new Response(
        JSON.stringify(
          success(next, next.pending ? "awaiting_response" : "done"),
        ),
        { status: 200 },
      );
    }
    if (path.endsWith("/end"))
      return new Response(
        JSON.stringify(success(reviewState, "awaiting_response")),
        {
          status: 200,
        },
      );
    if (path.endsWith("/package")) {
      const form = init?.body;
      assert.ok(form instanceof FormData);
      assert.equal(form.get("state"), JSON.stringify(finalState));
      assert.equal(form.has("specification"), false);
      assert.deepEqual(
        (form.getAll("files") as File[]).map((file) => file.name),
        ["notes.txt"],
      );
      return new Response(
        new Blob(["zip bytes"], { type: "application/zip" }),
        {
          status: 200,
          headers: {
            "content-type": "application/zip",
            "Content-Disposition":
              'attachment; filename="20261016-223045-interview.zip"',
          },
        },
      );
    }
    throw new Error(`Unexpected API path: ${path}`);
  };

  const repository = new InterviewRepository();
  const policy = new File(["policy original"], "policy.md", {
    type: "text/markdown",
  });
  const notes = new File(["notes original"], "notes.txt", {
    type: "text/plain",
  });
  const extracted = await api.extractDocuments([policy, notes]);
  const documents: InterviewDocument[] = extracted.documents;
  const started = await api.start(
    "A support assistant",
    { known_capability_ids: [], confidence: "low" },
    "end_user",
    documents,
  );
  let record = emptyRecord(
    "offline-flow",
    started.state,
    started.stage,
    startTranscript("A support assistant", started.state),
  );
  record = addFixtures(record, [policy, notes]);
  await repository.put(record);
  record = removeUnreferencedFixtures(record, ["policy.md", "notes.txt"]);
  assert.deepEqual(
    record.fixtures.map((file) => file.name),
    ["policy.md", "notes.txt"],
  );
  assert.equal(fixturesForSpecification(record).length, 0);
  const reloadedStart = await new InterviewRepository().read("offline-flow");
  assert.deepEqual(reloadedStart?.state.context.documents, initialDocuments);
  assert.deepEqual(
    reloadedStart?.fixtures.map((file) => file.name),
    ["policy.md", "notes.txt"],
  );
  record = reloadedStart!;
  let ended = applyEnd(record, await api.end(record.state));
  assert.deepEqual(toPresentation(ended).requests.at(-1), reviewState.pending);
  const skipped = ended.transcript[1];
  assert.equal(
    skipped?.kind === "interaction" ? skipped.status : undefined,
    "ended_unanswered",
  );
  await repository.put(ended);
  ended = (await new InterviewRepository().read(ended.id))!;
  assert.equal(ended.state.pending?.request_id, "review-1");
  assert.deepEqual(toPresentation(ended).requests.at(-1), reviewState.pending);
  assert.equal(toPresentation(ended).done, false);
  const operations = new InterviewOperations(repository, (saved) => {
    ended = saved;
  });
  const selection: UserResponse = {
    type: "choice",
    values: { "files:S-1": ["notes.txt"] },
  };
  await operations.send(ended, selection, [], ["policy.md"]);
  assert.deepEqual(
    toPresentation(ended).requests.at(-1),
    selectedState.pending,
  );
  assert.deepEqual(
    ended.fixtures.map((file) => file.name),
    ["policy.md", "notes.txt"],
  );
  const confirm: UserResponse = { type: "choice", selected: ["continue"] };
  await operations.send(ended, confirm);
  assert.equal(toPresentation(ended).done, true);
  const withFixture = addFixtures(ended, [
    new File(["unused later file"], "unused.json", {
      type: "application/json",
    }),
  ]);
  await repository.put(withFixture);
  const archive = await api.package(
    { state: withFixture.state },
    fixturesForSpecification(withFixture),
  );
  assert.equal(await archive.blob.text(), "zip bytes");
  const downloads: string[] = [];
  downloadArchive(
    archive,
    {
      createElement: () => ({
        href: "",
        download: "",
        click() {
          downloads.push(this.download);
        },
        remove() {},
      }),
    } as unknown as Document,
    { createObjectURL: () => "blob:offline", revokeObjectURL: () => {} },
  );
  assert.deepEqual(downloads, ["20261016-223045-interview.zip"]);
  assert.equal(withFixture.state.confirmed, true);
  assert.equal(withFixture.transcript.at(-1)?.kind, "interaction");
  await repository.delete("offline-flow");
});

test("runs an offline start, chat, choice, form, reload, end and package flow", async () => {
  const startState = baseState();
  const choice = choiceRequest();
  const form = formRequest();
  const finalState: InterviewState = {
    ...startState,
    pending: null,
    confirmed: true,
    specification: {
      ...startState.specification,
      tasks: [policyTask(["policy.pdf"])],
    },
  };

  globalThis.fetch = async (input, init) => {
    const path = String(input);
    if (path.endsWith("/start"))
      return new Response(
        JSON.stringify(success(startState, "awaiting_response")),
        { status: 200 },
      );
    if (path.endsWith("/turn")) {
      const body = JSON.parse(String(init?.body)) as { request_id: string };
      const next =
        body.request_id === "chat-1"
          ? { ...startState, pending: choice }
          : body.request_id === "choice-1"
            ? { ...startState, pending: form }
            : finalState;
      return new Response(
        JSON.stringify(
          success(next, next.pending ? "awaiting_response" : "done"),
        ),
        { status: 200 },
      );
    }
    if (path.endsWith("/end"))
      return new Response(JSON.stringify(success(finalState, "done")), {
        status: 200,
      });
    if (path.endsWith("/package")) {
      const body = init?.body;
      assert.ok(body instanceof FormData);
      assert.equal(body.get("state"), JSON.stringify(finalState));
      assert.equal(body.has("specification"), false);
      assert.deepEqual(
        (body.getAll("files") as File[]).map((file) => file.name),
        ["policy.pdf"],
      );
      return new Response(
        new Blob(["zip bytes"], { type: "application/zip" }),
        {
          status: 200,
          headers: {
            "content-type": "application/zip",
            "Content-Disposition":
              'attachment; filename="20261016-223045-manual.zip"',
          },
        },
      );
    }
    throw new Error(`Unexpected API path: ${path}`);
  };

  const repository = new InterviewRepository();
  const started = await api.start("A support assistant", {
    known_capability_ids: [],
    confidence: "low",
  });
  assert.deepEqual(started.state.context.documents ?? [], []);
  let record = emptyRecord(
    "offline-plain-flow",
    started.state,
    started.stage,
    startTranscript("A support assistant", started.state),
  );
  await repository.put(record);
  record = applyTurn(
    record,
    await api.respond(record.state, "chat-1", {
      type: "chat",
      text: "It answers questions",
    }),
    { type: "chat", text: "It answers questions" },
  );
  record = applyTurn(
    record,
    await api.respond(record.state, "choice-1", {
      type: "choice",
      selected: ["continue"],
    }),
    { type: "choice", selected: ["continue"] },
  );
  record = applyTurn(
    record,
    await api.respond(record.state, "form-1", {
      type: "form",
      cancelled: false,
      values: { name: "Reviewer" },
    }),
    { type: "form", cancelled: false, values: { name: "Reviewer" } },
  );
  await repository.put(record);

  const reloaded = await new InterviewRepository().read("offline-plain-flow");
  assert.equal(reloaded?.transcript.length, 4);
  const ended = applyEnd(reloaded!, await api.end(reloaded!.state));
  const withFixture = addFixtures(ended, [
    new File(["fixture bytes"], "policy.pdf", { type: "application/pdf" }),
    new File(["unused later file"], "unused.json", {
      type: "application/json",
    }),
  ]);
  await repository.put(withFixture);
  assert.deepEqual(
    withFixture.fixtures.map((file) => file.name),
    ["policy.pdf", "unused.json"],
  );
  const archive = await api.package(
    { state: withFixture.state },
    fixturesForSpecification(withFixture),
  );
  assert.equal(await archive.blob.text(), "zip bytes");
  const downloads: string[] = [];
  downloadArchive(
    archive,
    {
      createElement: () => ({
        href: "",
        download: "",
        click() {
          downloads.push(this.download);
        },
        remove() {},
      }),
    } as unknown as Document,
    { createObjectURL: () => "blob:offline", revokeObjectURL: () => {} },
  );
  assert.deepEqual(downloads, ["20261016-223045-manual.zip"]);
  assert.equal(withFixture.state.confirmed, true);
  assert.equal(withFixture.transcript.at(-1)?.kind, "interaction");
  await repository.delete("offline-plain-flow");
});
