import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { synthesizeManualSpecification } from "../manual.ts";
import { api, TransportError, type InterviewState } from "./api.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

const state = {
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
  pending: null,
} as InterviewState;
const success = {
  type: "success",
  state,
  stage: "clarify",
  missing: [],
  outcome: "awaiting_response",
} as const;

test("uses the stateless wizard routes and JSON request shapes", async () => {
  const calls: Array<{ path: string; body: unknown }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({
      path: String(input),
      body:
        init?.body === undefined || init.body instanceof FormData
          ? init?.body
          : JSON.parse(String(init.body)),
    });
    if (String(input) === "/api/v1/wizard/package") {
      return new Response("zip bytes", {
        headers: {
          "content-type": "application/zip",
          "Content-Disposition":
            'attachment; filename="20261016-223045-interview.zip"',
        },
      });
    }
    return new Response(JSON.stringify(success), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await api.start("A support assistant", {
    known_capability_ids: [],
    confidence: "low",
  });
  await api.respond(state, "request-1", {
    type: "chat",
    text: "It answers questions",
  });
  await api.end(state);
  await api.compile(state.specification);
  await api.graders();
  await api.config();
  await api.package({ state }, []);

  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/v1/wizard/interview/start",
      "/api/v1/wizard/interview/turn",
      "/api/v1/wizard/interview/end",
      "/api/v1/wizard/compile",
      "/api/v1/graders",
      "/api/v1/wizard/config",
      "/api/v1/wizard/package",
    ],
  );
  assert.deepEqual(calls[0]?.body, {
    description: "A support assistant",
    perspective: "end_user",
    known_capability_ids: [],
    capability_confidence: "low",
    documents: [],
  });
  assert.deepEqual(calls[1]?.body, {
    state,
    request_id: "request-1",
    response: { type: "chat", text: "It answers questions" },
  });
  assert.deepEqual(calls[2]?.body, { state });
  assert.deepEqual(calls[3]?.body, state.specification);
});

test("sends the selected perspective and capability evidence when an Interview begins", async () => {
  let body: unknown;
  globalThis.fetch = async (_input, init) => {
    body = JSON.parse(String(init?.body));
    return new Response(JSON.stringify(success), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await api.start(
    "A support assistant",
    { known_capability_ids: ["tool_use"], confidence: "medium" },
    "security",
    [
      {
        name: "policy.md",
        text: "Keep user data private.",
      },
    ],
  );

  assert.deepEqual(body, {
    description: "A support assistant",
    perspective: "security",
    known_capability_ids: ["tool_use"],
    capability_confidence: "medium",
    documents: [
      {
        name: "policy.md",
        text: "Keep user data private.",
      },
    ],
  });
});

test("extracts selected interview files as an ordered multipart request", async () => {
  let received: FormData | undefined;
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "/api/v1/wizard/documents/extract");
    assert.equal(init?.method, "POST");
    assert.ok(init?.body instanceof FormData);
    received = init.body;
    return new Response(
      JSON.stringify({
        documents: [
          { name: "first.md", text: "First" },
          { name: "second.txt", text: "Second" },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };

  const result = await api.extractDocuments([
    new File(["First"], "first.md"),
    new File(["Second"], "second.txt"),
  ]);

  assert.deepEqual(result.documents, [
    { name: "first.md", text: "First" },
    { name: "second.txt", text: "Second" },
  ]);
  assert.deepEqual(
    (received?.getAll("files") as File[]).map((file) => file.name),
    ["first.md", "second.txt"],
  );
});

test("preserves extraction failure details", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        type: "failure",
        code: "encrypted_pdf",
        message: "locked.pdf: The PDF is encrypted.",
        retryable: false,
      }),
      { status: 400, headers: { "content-type": "application/json" } },
    );

  await assert.rejects(
    api.extractDocuments([new File(["locked"], "locked.pdf")]),
    (cause: unknown) =>
      cause instanceof TransportError &&
      cause.status === 400 &&
      !cause.retryable &&
      cause.code === "encrypted_pdf" &&
      cause.message.includes("locked.pdf"),
  );
});

test("packages a synthesized manual Specification and its fixtures as multipart", async () => {
  let received: FormData | undefined;
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), "/api/v1/wizard/package");
    assert.equal(init?.method, "POST");
    assert.ok(init?.body instanceof FormData);
    received = init?.body as FormData;
    return new Response(new Blob(["zip bytes"], { type: "application/zip" }), {
      status: 200,
      headers: {
        "content-type": "application/zip",
        "Content-Disposition":
          'attachment; filename="20261016-223045-manual.zip"',
      },
    });
  };

  const specification = synthesizeManualSpecification({
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
        fixtures: ["policy.pdf"],
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
  });
  const policy = new File(["policy"], "policy.pdf", {
    type: "application/pdf",
  });
  const archive = await api.package({ specification }, [
    { name: policy.name, blob: policy },
  ]);

  assert.equal(await archive.blob.text(), "zip bytes");
  assert.equal(received?.get("specification"), JSON.stringify(specification));
  assert.equal((received?.get("files") as File).name, "policy.pdf");
});

test("package failures preserve the API error shape", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        type: "failure",
        code: "compilation_failed",
        message: "Missing fixture file(s): policy.pdf.",
        retryable: false,
      }),
      { status: 400, headers: { "content-type": "application/json" } },
    );

  await assert.rejects(
    api.package({ state }, []),
    (cause: unknown) =>
      cause instanceof TransportError &&
      cause.status === 400 &&
      cause.code === "compilation_failed" &&
      !cause.retryable,
  );
});

for (const status of [400, 422, 500, 503]) {
  test(`turn failures preserve HTTP ${status} and retry metadata`, async () => {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          type: "failure",
          code: "service_error",
          message: "Try again",
          retryable: status >= 500,
        }),
        { status, headers: { "content-type": "application/json" } },
      );
    await assert.rejects(
      api.respond(state, "request-1", { type: "chat", text: "retry" }),
      (cause: unknown) =>
        cause instanceof TransportError &&
        cause.status === status &&
        cause.retryable === status >= 500,
    );
  });
}

test("typed failures in a successful HTTP response are still surfaced", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        type: "failure",
        code: "invalid_response",
        message: "The response is invalid.",
        retryable: false,
      }),
      { status: 200 },
    );
  await assert.rejects(
    api.start("bad", { known_capability_ids: [], confidence: "low" }),
    (cause: unknown) =>
      cause instanceof TransportError &&
      cause.code === "invalid_response" &&
      !cause.retryable,
  );
});
