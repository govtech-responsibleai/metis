import assert from "node:assert/strict";
import { test } from "node:test";
import {
  bindingFromDraft,
  emptyConnectionDraft,
  errorsByField,
  startConnection,
  submissionHints,
  type ConnectionDraft,
} from "./connection.ts";
import type { ConnectionCheckResult } from "./transport/api.ts";

const http: ConnectionDraft = {
  ...emptyConnectionDraft(),
  mode: "run",
  name: " Policy assistant ",
  specUrl: "${APP_URL}/openapi.json",
  secretEnv: "APP_KEY",
  secretHeaders: "POST /chat X-Api-Key APP_HEADER",
  forbiddenCalls: "DELETE /**",
  tlsVerify: false,
  startUrl: "https://ignored.example",
};

const valid = (draft: ConnectionDraft): ConnectionCheckResult => ({
  binding: bindingFromDraft(draft) as ConnectionCheckResult["binding"],
  errors: [],
  live: false,
  probes: [],
  status: "unchecked",
});

test("an HTTP draft becomes binding fields with no browser field", () => {
  assert.deepEqual(bindingFromDraft(http), {
    schema_version: 1,
    identity: { name: "Policy assistant" },
    transport: "http",
    spec_url: "${APP_URL}/openapi.json",
    auth: { secret_env: "APP_KEY" },
    secret_headers: [
      { match: "POST /chat", header: "X-Api-Key", env: "APP_HEADER" },
    ],
    forbidden_calls: ["DELETE /**"],
    tls_verify: false,
  });
});

test("a browser draft sends the sign-in note and its variable names only", () => {
  const binding = bindingFromDraft({
    ...http,
    transport: "browser",
    startUrl: "${APP_URL}/login",
    loginNote: "Type {{secret:APP_USER}}.",
    loginSecrets: "APP_USER, APP_PASSWORD",
  });
  assert.deepEqual(binding, {
    schema_version: 1,
    identity: { name: "Policy assistant" },
    transport: "browser",
    start_url: "${APP_URL}/login",
    login: {
      note: "Type {{secret:APP_USER}}.",
      secrets: ["APP_USER", "APP_PASSWORD"],
    },
  });
});

test("each problem from a test shows under the field to fix", () => {
  const draft: ConnectionDraft = {
    ...http,
    specUrl: "${APP_URL}/openapi.json",
    secretHeaders: "POST /chat X-Api-Key APP_HEADER",
  };
  const errors = errorsByField(draft, {
    binding: null,
    errors: [
      {
        loc: ["auth", "secret_env"],
        msg: "String should match pattern '^[A-Z_][A-Z0-9_]*$'",
      },
      {
        loc: ["identity", "name"],
        msg: "String should have at least 1 character",
      },
      { loc: [], msg: "Value error, a http binding needs spec_url" },
    ],
    live: true,
    probes: [
      { name: "APP_KEY", ok: false, message: "not set" },
      { name: "APP_HEADER", ok: false, message: "not set" },
      { name: "APP_URL", ok: false, message: "not set" },
      { name: "server", ok: false, message: "the server did not answer" },
      {
        name: "spec_url",
        ok: true,
        message: "OpenAPI document: App, 2 endpoints",
      },
    ],
    status: "unchecked",
  });
  assert.equal(
    errors.secretEnv,
    "Use a variable name in capital letters, digits, and _, such as APP_API_KEY. APP_KEY is not set. Set it in .env.",
  );
  assert.equal(errors.name, "Required");
  assert.equal(errors.secretHeaders, "APP_HEADER is not set. Set it in .env.");
  assert.equal(
    errors.specUrl,
    "APP_URL is not set. Set it in .env. The OpenAPI document loads, but the server did not answer.",
  );
  assert.equal(errors.binding, "a http binding needs spec_url");
});

test("the Interview starts with a connection only in run mode with a valid binding", () => {
  assert.equal(startConnection({ ...http, mode: "spec" }, valid(http)), null);
  assert.equal(startConnection(http, valid(http))?.transport, "http");
  assert.equal(
    startConnection(http, {
      binding: null,
      errors: [{ loc: ["identity", "name"], msg: "too short" }],
      live: false,
      status: "unchecked",
    }),
    null,
  );
});

test("sign-in variables with no sign-in steps still reach the check", () => {
  const binding = bindingFromDraft({
    ...http,
    transport: "browser",
    startUrl: "${APP_URL}/login",
    loginSecrets: "APP_USER",
  });
  assert.deepEqual(binding.login, { note: "", secrets: ["APP_USER"] });
});

test("the test result warns about a submission and offers the suggested ones", () => {
  const draft: ConnectionDraft = { ...http, submissions: "POST /chats" };
  const result: ConnectionCheckResult = {
    ...valid(draft),
    warnings: [
      {
        loc: ["submissions", 0],
        msg: "POST /chats matches no call in the OpenAPI document.",
      },
    ],
    suggested_submissions: ["POST /conversations/*/messages"],
  };

  assert.deepEqual(submissionHints(draft, result), {
    warning: "POST /chats matches no call in the OpenAPI document.",
    suggestion: ["POST /conversations/*/messages"],
  });
  // once the draft holds the suggestion, it is not offered again
  assert.deepEqual(
    submissionHints(
      { ...draft, submissions: "POST /conversations/*/messages" },
      { ...result, warnings: [] },
    ),
    { warning: null, suggestion: [] },
  );
  assert.deepEqual(submissionHints(draft, null), {
    warning: null,
    suggestion: [],
  });
});
