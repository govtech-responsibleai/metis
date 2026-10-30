// The target connection draft for the connection step. The browser only collects the values and
// shapes them as binding fields. The API validates them; this module repeats no binding rule.
import type {
  ConnectionCheckResult,
  ConnectionTransport,
  TargetConnection,
} from "./transport/api";

export type ConnectionMode = "spec" | "run";

export interface ConnectionDraft {
  mode: ConnectionMode;
  transport: ConnectionTransport;
  name: string;
  specUrl: string;
  secretEnv: string;
  // one header per line: METHOD /path HEADER ENV_NAME
  secretHeaders: string;
  forbiddenCalls: string;
  submissions: string;
  tlsVerify: boolean;
  startUrl: string;
  loginNote: string;
  loginSecrets: string;
  notes: string;
}

export const emptyConnectionDraft = (): ConnectionDraft => ({
  mode: "spec",
  transport: "http",
  name: "",
  specUrl: "",
  secretEnv: "",
  secretHeaders: "",
  forbiddenCalls: "",
  submissions: "",
  tlsVerify: true,
  startUrl: "",
  loginNote: "",
  loginSecrets: "",
  notes: "",
});

function list(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

// Lines that do not have four parts are sent as they are, so the API reports the field.
function secretHeaders(value: string): Array<Record<string, string>> {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [method = "", path = "", header = "", env = "", ...rest] =
        line.split(/\s+/);
      return rest.length === 0 && env
        ? { match: `${method} ${path}`, header, env }
        : { match: line, header: "", env: "" };
    });
}

// Leave out empty optional fields. A browser binding then sends no HTTP field, and the reverse.
export function bindingFromDraft(
  draft: ConnectionDraft,
): Record<string, unknown> {
  const binding: Record<string, unknown> = {
    schema_version: 1,
    identity: { name: draft.name.trim() },
    transport: draft.transport,
  };
  if (draft.transport === "http") {
    binding.spec_url = draft.specUrl.trim();
    if (draft.secretEnv.trim())
      binding.auth = { secret_env: draft.secretEnv.trim() };
    const headers = secretHeaders(draft.secretHeaders);
    if (headers.length) binding.secret_headers = headers;
    const forbidden = list(draft.forbiddenCalls);
    if (forbidden.length) binding.forbidden_calls = forbidden;
    const submissions = list(draft.submissions);
    if (submissions.length) binding.submissions = submissions;
    if (!draft.tlsVerify) binding.tls_verify = false;
  } else {
    binding.start_url = draft.startUrl.trim();
    // login.note is required. Send the login block when either field has a value, so the API
    // reports a missing note and the variables are not dropped with no message.
    if (draft.loginNote.trim() || list(draft.loginSecrets).length)
      binding.login = {
        note: draft.loginNote.trim(),
        secrets: list(draft.loginSecrets),
      };
  }
  if (draft.notes.trim()) binding.advice = { notes: draft.notes.trim() };
  return binding;
}

// The connection to keep from a check result, or null when the binding is not valid.
export function connectionFromCheck(
  result: ConnectionCheckResult | null,
): TargetConnection | null {
  if (!result?.binding) return null;
  return {
    transport: result.binding.transport,
    binding: result.binding,
    status: result.status,
  };
}

// The draft field that an API field error belongs to, so the form can mark it.
export function draftFieldFor(
  loc: ReadonlyArray<string | number>,
): keyof ConnectionDraft | null {
  const [first, second] = loc.map(String);
  switch (first) {
    case "identity":
      return "name";
    case "spec_url":
      return "specUrl";
    case "start_url":
      return "startUrl";
    case "auth":
      return "secretEnv";
    case "secret_headers":
      return "secretHeaders";
    case "forbidden_calls":
      return "forbiddenCalls";
    case "submissions":
      return "submissions";
    case "login":
      return second === "secrets" ? "loginSecrets" : "loginNote";
    case "advice":
      return "notes";
    default:
      return null;
  }
}

// What the last test found about the submissions: patterns that match no call in the OpenAPI
// document, and the calls that the document suggests. A suggestion goes into the draft only when
// the user selects it, so the user always confirms it.
export function submissionHints(
  draft: ConnectionDraft,
  result: ConnectionCheckResult | null,
): { warning: string | null; suggestion: string[] } {
  const warning =
    (result?.warnings ?? [])
      .filter((item) => draftFieldFor(item.loc) === "submissions")
      .map((item) => item.msg)
      .join(" ") || null;
  const suggestion = result?.suggested_submissions ?? [];
  const current = list(draft.submissions);
  const same =
    suggestion.length === current.length &&
    suggestion.every((item) => current.includes(item));
  return { warning, suggestion: same ? [] : suggestion };
}

// The connection to start the Interview with, from the check result. Spec-only mode starts with
// no connection. Run mode starts only with a valid binding.
export function startConnection(
  draft: ConnectionDraft,
  result: ConnectionCheckResult | null,
): TargetConnection | null {
  return draft.mode === "spec" ? null : connectionFromCheck(result);
}

function fieldMessage(msg: string): string {
  // Pydantic says "String should have at least 1 character" for an empty field.
  if (/at least 1 character/.test(msg)) return "Required";
  if (/should match pattern/.test(msg))
    return "Use a variable name in capital letters, digits, and _, such as APP_API_KEY.";
  return msg.replace(/^Value error, /, "");
}

// The field that a failed live check belongs to. A variable check is named after the variable,
// so it goes to the field that names that variable.
function probeField(
  draft: ConnectionDraft,
  name: string,
): keyof ConnectionDraft | null {
  if (name === "spec_url" || name === "server") return "specUrl";
  if (name === "start_url") return "startUrl";
  if (draft.secretEnv.trim() === name) return "secretEnv";
  if (list(draft.loginSecrets).includes(name)) return "loginSecrets";
  if (secretHeaders(draft.secretHeaders).some((header) => header.env === name))
    return "secretHeaders";
  if (draft.specUrl.includes(`\${${name}}`)) return "specUrl";
  if (draft.startUrl.includes(`\${${name}}`)) return "startUrl";
  return null;
}

function probeMessage(name: string, message: string): string {
  if (message === "not set") return `${name} is not set. Set it in .env.`;
  if (name === "server") return `The OpenAPI document loads, but ${message}.`;
  return message.charAt(0).toUpperCase() + message.slice(1) + ".";
}

// Every problem from the last test, under the field to fix. A problem with no field goes to
// "binding", which shows under the form.
export function errorsByField(
  draft: ConnectionDraft,
  result: ConnectionCheckResult | null,
): Partial<Record<keyof ConnectionDraft | "binding", string>> {
  const errors: Partial<Record<keyof ConnectionDraft | "binding", string>> = {};
  const add = (field: keyof ConnectionDraft | "binding", message: string) => {
    errors[field] = errors[field] ? `${errors[field]} ${message}` : message;
  };
  for (const error of result?.errors ?? [])
    add(draftFieldFor(error.loc) ?? "binding", fieldMessage(error.msg));
  for (const probe of result?.probes ?? [])
    if (!probe.ok)
      add(
        probeField(draft, probe.name) ?? "binding",
        probeMessage(probe.name, probe.message),
      );
  return errors;
}
