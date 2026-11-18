import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { synthesizeManualSpecification } from "../manual.ts";
import {
  api,
  auth,
  dispositionFilename,
  onLoginRequired,
  store,
  TransportError,
  users,
  type InterviewState,
  type Report,
} from "./api.ts";

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
            'attachment; filename="20261016-223045-interview-k7mwp.zip"',
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
          'attachment; filename="20261016-223045-manual-k7mwp.zip"',
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

const REPORT_NAME =
  "inline; filename=\"run_1-report.html\"; filename*=UTF-8''run%201-report.html";

test("report reads report.json of the experiment", async () => {
  const report = { target: "Bank bot" } as Report;
  let path = "";
  globalThis.fetch = async (input) => {
    path = String(input);
    return new Response(JSON.stringify(report), {
      headers: { "content-type": "application/json" },
    });
  };

  assert.deepEqual(await api.report("run 1/a"), report);
  assert.equal(path, "/api/v1/insights/run%201%2Fa/report");
});

test("reportPage gives report.html with the name from the header", async () => {
  let path = "";
  globalThis.fetch = async (input) => {
    path = String(input);
    return new Response("<html></html>", {
      headers: {
        "content-type": "text/html",
        "Content-Disposition": REPORT_NAME,
      },
    });
  };

  const page = await api.reportPage("run 1");

  assert.equal(path, "/api/v1/insights/run%201/report.html");
  assert.equal(page.filename, "run 1-report.html");
  assert.equal(await page.blob.text(), "<html></html>");
});

test("simulate posts the input folder", async () => {
  let path = "";
  let init: RequestInit | undefined;
  globalThis.fetch = async (input, options) => {
    path = String(input);
    init = options;
    return new Response(JSON.stringify({ experiment_id: "spec-1" }), {
      status: 202,
    });
  };

  assert.deepEqual(await api.simulate("evaluations/specifications/t1"), {
    experiment_id: "spec-1",
  });
  assert.equal(path, "/api/v1/engine/simulate");
  assert.equal(init?.method, "POST");
  assert.equal(init?.body, '{"input_dir":"evaluations/specifications/t1"}');
});

test("a refused start keeps the code, the message and the retry flag of the API", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        type: "failure",
        code: "model_unavailable",
        message: "Set the model key.",
        retryable: true,
      }),
      { status: 503 },
    );

  await assert.rejects(
    api.simulate("evaluations/specifications/t1"),
    (cause) =>
      cause instanceof TransportError &&
      cause.status === 503 &&
      cause.code === "model_unavailable" &&
      cause.message === "Set the model key." &&
      cause.retryable,
  );
});

test("the engine reads go to the routes of the experiment", async () => {
  const paths: string[] = [];
  globalThis.fetch = async (input) => {
    paths.push(String(input));
    return new Response("[]");
  };

  await store.experiments("t/1");
  await store.specification("t/1");
  await api.engineStatus("e 1");
  await api.engineEvents("e 1");
  await api.engineEvents("e 1", 7);
  await api.doctor();

  assert.deepEqual(paths, [
    "/api/v1/engine/experiments?target_id=t%2F1",
    "/api/v1/targets/t%2F1/specification",
    "/api/v1/engine/e%201",
    "/api/v1/engine/e%201/events",
    "/api/v1/engine/e%201/events?after=7",
    "/api/v1/doctor",
  ]);
});

test("the run actions and the row saves go to their routes", async () => {
  const calls: string[] = [];
  globalThis.fetch = async (input, init) => {
    calls.push(
      `${init?.method ?? "GET"} ${String(input)} ${String(init?.body ?? "")}`.trim(),
    );
    return new Response("{}", { status: 202 });
  };

  await api.stop("e1");
  await api.resumeSimulation("e1");
  await api.evaluate("e1");
  await api.resumeEvaluation("e1");
  await store.experiment("e1");
  await store.putExperiment("e1", { target_id: "t1", step: "evaluate" });
  await store.deleteExperiment("e1");

  assert.deepEqual(calls, [
    "POST /api/v1/engine/e1/stop",
    "POST /api/v1/engine/simulate/e1/resume",
    "POST /api/v1/engine/evaluate/e1",
    "POST /api/v1/engine/evaluate/e1/resume",
    "GET /api/v1/engine/experiments/e1",
    'PUT /api/v1/engine/experiments/e1 {"target_id":"t1","step":"evaluate"}',
    "DELETE /api/v1/engine/experiments/e1",
  ]);
});

test("the exact file name comes before the ASCII fallback", () => {
  assert.equal(dispositionFilename(REPORT_NAME), "run 1-report.html");
  assert.equal(
    dispositionFilename('attachment; filename="a \\"b\\".zip"'),
    'a "b".zip',
  );
  assert.equal(
    dispositionFilename(
      "inline; filename=\"a.html\"; filename*=UTF-8''%E0%A4%A",
    ),
    "a.html",
  );
  assert.equal(dispositionFilename("inline"), null);
  assert.equal(dispositionFilename(null), null);
});

test("a file with no safe name is refused", async () => {
  for (const disposition of [
    null,
    'inline; filename="report.txt"',
    'inline; filename=".html"',
    "inline; filename*=UTF-8''..%2Freport.html",
  ]) {
    globalThis.fetch = async () =>
      new Response("<html></html>", {
        headers: disposition ? { "Content-Disposition": disposition } : {},
      });
    await assert.rejects(
      api.reportPage("e1"),
      /no valid file name/,
      String(disposition),
    );
  }
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

function failure(status: number, code: string, message: string): Response {
  return new Response(
    JSON.stringify({ type: "failure", code, message, retryable: false }),
    { status, headers: { "content-type": "application/json" } },
  );
}

test("a request without a login session tells the login gate", async () => {
  let asked = 0;
  const stop = onLoginRequired(() => {
    asked += 1;
  });
  globalThis.fetch = async () =>
    failure(401, "login_required", "Log in to use this METIS server.");

  await assert.rejects(store.targets(), (error: unknown) => {
    assert.ok(error instanceof TransportError);
    assert.equal(error.status, 401);
    assert.equal(error.code, "login_required");
    return true;
  });
  assert.equal(asked, 1);

  stop();
  await assert.rejects(store.targets());
  assert.equal(asked, 1);
});

test("wrong credentials do not tell the login gate", async () => {
  let asked = 0;
  const stop = onLoginRequired(() => {
    asked += 1;
  });
  globalThis.fetch = async () =>
    failure(
      401,
      "invalid_credentials",
      "The username or the password is not correct.",
    );

  await assert.rejects(auth.login("curious-otter", "wrong"), {
    message: "The username or the password is not correct.",
  });
  assert.equal(asked, 0);
  stop();
});

test("login sends the credentials as JSON and logout sends a POST", async () => {
  const calls: Array<{ path: string; method?: string; body: unknown }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({
      path: String(input),
      method: init?.method,
      body:
        init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    return new Response(
      init?.body === undefined
        ? null
        : JSON.stringify({ login: true, user: { username: "curious-otter" } }),
      { status: init?.body === undefined ? 204 : 200 },
    );
  };

  const current = await auth.login("curious-otter", "k7mwp-3xr9t");
  await auth.logout();

  assert.equal(current.user?.username, "curious-otter");
  assert.deepEqual(calls, [
    {
      path: "/api/v1/auth/login",
      method: "POST",
      body: { username: "curious-otter", password: "k7mwp-3xr9t" },
    },
    { path: "/api/v1/auth/logout", method: "POST", body: undefined },
  ]);
});

test("a join sends the join token as a bearer token", async () => {
  let asked = 0;
  const stop = onLoginRequired(() => {
    asked += 1;
  });
  const calls: Array<{ path: string; method?: string; auth: string | null }> =
    [];
  globalThis.fetch = async (input, init) => {
    calls.push({
      path: String(input),
      method: init?.method,
      auth: new Headers(init?.headers).get("Authorization"),
    });
    return calls.length === 1
      ? new Response(
          JSON.stringify({
            id: "u1",
            username: "brave-otter",
            created_at: "2026-11-17T00:00:00Z",
            admin: false,
            password: "k3m7p-x9q2r",
          }),
          { status: 201 },
        )
      : failure(401, "invalid_admin_token", "The request needs the token.");
  };

  const account = await users.join("workshop-token");
  await assert.rejects(users.join("wrong"), { status: 401 });

  assert.equal(account.password, "k3m7p-x9q2r");
  assert.deepEqual(calls, [
    { path: "/api/v1/users", method: "POST", auth: "Bearer workshop-token" },
    { path: "/api/v1/users", method: "POST", auth: "Bearer wrong" },
  ]);
  assert.equal(asked, 0);
  stop();
});

test("the admin calls use the login session and no token", async () => {
  const calls: Array<{
    path: string;
    method?: string;
    auth: string | null;
    body: unknown;
  }> = [];
  const account = {
    id: "u1",
    username: "brave-otter",
    created_at: "2026-11-17T00:00:00Z",
    admin: true,
  };
  globalThis.fetch = async (input, init) => {
    calls.push({
      path: String(input),
      method: init?.method,
      auth: new Headers(init?.headers).get("Authorization"),
      body:
        init?.body === undefined ? undefined : JSON.parse(String(init.body)),
    });
    return new Response(
      JSON.stringify(
        init?.method === "POST"
          ? { ...account, password: "k3m7p-x9q2r" }
          : { users: [account] },
      ),
      { status: init?.method === "POST" ? 201 : 200 },
    );
  };

  assert.deepEqual(await users.list(), { users: [account] });
  assert.equal((await users.create(true)).password, "k3m7p-x9q2r");
  assert.equal(
    (await users.resetPassword("brave otter")).password,
    "k3m7p-x9q2r",
  );

  assert.deepEqual(calls, [
    { path: "/api/v1/users", method: undefined, auth: null, body: undefined },
    {
      path: "/api/v1/users",
      method: "POST",
      auth: null,
      body: { admin: true },
    },
    {
      path: "/api/v1/users/brave%20otter/password",
      method: "POST",
      auth: null,
      body: undefined,
    },
  ]);
});
