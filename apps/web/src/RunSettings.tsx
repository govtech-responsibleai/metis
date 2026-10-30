// Model settings in the browser: the start check for the interview role, and the run
// settings step after the last review. The browser never sees a key or a URL. `GET /models`
// returns names and status only, and the run settings step writes model names only.

import type {
  InterviewState,
  ModelRole,
  ModelStatus,
  Specification,
} from "./transport/api";
import { Button, Mono, Panel } from "./ui";

export const MODEL_GUIDE = "docs/guide/models.md";

// The roles whose model a Specification records. The interview role stays in the
// environment, so the run settings step does not show it.
export type RunModelRole = Extract<
  ModelRole,
  "user_agent" | "runner_agent" | "judge"
>;
export type RunModels = Partial<Record<RunModelRole, string>>;

const DEFAULT_FIELD: Record<
  RunModelRole,
  "user_agent_model" | "runner_agent_model" | "judge_model"
> = {
  user_agent: "user_agent_model",
  runner_agent: "runner_agent_model",
  judge: "judge_model",
};

const ROLE_HELP: Record<RunModelRole, string> = {
  user_agent:
    "Acts as a real user. Use a capable model that is different from your target.",
  runner_agent:
    "Works out how to act on the target for a generic runner. Empty uses the user agent model.",
  judge:
    "Scores each criterion. Use a model from a different family than your target.",
};

// The roles that a run of this Specification calls. The runner agent runs only for a generic
// runner, which a target binding selects.
/**
 * The model that a run uses when the field of `role` stays empty. It matches the engine: the
 * runner agent uses `RUNNER_AGENT_MODEL` when it is set, else the user agent model of the run,
 * so its placeholder follows the typed user agent value.
 */
export function placeholderModel(
  role: RunModelRole,
  statuses: readonly ModelStatus[],
  values: RunModels,
): string {
  const byRole = new Map(statuses.map((status) => [status.role, status]));
  const status = byRole.get(role);
  if (role === "runner_agent" && status?.source === "user agent model") {
    return (
      values.user_agent?.trim() ||
      byRole.get("user_agent")?.model ||
      status.model
    );
  }
  return status?.model ?? "";
}

export function runRoles(specification: Specification): RunModelRole[] {
  return specification.target_binding
    ? ["user_agent", "runner_agent", "judge"]
    : ["user_agent", "judge"];
}

// The model names that the Specification records now.
export function runModels(specification: Specification): RunModels {
  const defaults = specification.defaults ?? {};
  const models: RunModels = {};
  for (const role of Object.keys(DEFAULT_FIELD) as RunModelRole[]) {
    const value = defaults[DEFAULT_FIELD[role]];
    if (value) models[role] = value;
  }
  return models;
}

// Write model names into the Specification defaults. A blank name removes the default, so the
// run uses the environment. No other field changes.
export function withRunModels(
  state: InterviewState,
  models: RunModels,
): InterviewState {
  const defaults = { ...(state.specification.defaults ?? {}) };
  for (const role of Object.keys(models) as RunModelRole[]) {
    const name = models[role]?.trim();
    if (name) defaults[DEFAULT_FIELD[role]] = name;
    else delete defaults[DEFAULT_FIELD[role]];
  }
  return { ...state, specification: { ...state.specification, defaults } };
}

// The state to package when the user continues from the run settings step. With no draft, the
// user changed nothing, so the state, and so the ZIP, stays the same.
export function stateForDownload(
  state: InterviewState,
  drafts: RunModels | null,
): InterviewState {
  return drafts ? withRunModels(state, drafts) : state;
}

// Whether the Interview can start. Only the interview role is required. The run roles are needed
// only for `metis engine run`.
export function interviewReady(statuses: readonly ModelStatus[]): boolean {
  return !statuses.some(
    (status) => status.role === "interview" && !status.configured,
  );
}

// The text on the greyed-out start control while the interview role has no key.
export const START_BLOCKED = "Configure API keys to start interview";

// The run settings step: one model name for each role that the run calls. It comes after the
// last review and before the download. It is controlled, so the caller keeps the draft, saves it
// into the client-held state, and starts the download when the user continues.
export function RunSettings({
  roles,
  statuses,
  values,
  busy,
  onChange,
  onContinue,
  onBack,
}: {
  roles: readonly RunModelRole[];
  statuses: readonly ModelStatus[];
  values: RunModels;
  busy: boolean;
  onChange: (role: RunModelRole, value: string) => void;
  onContinue: () => void;
  // Reopens the last review of the Interview.
  onBack?: () => void;
}) {
  const byRole = new Map(statuses.map((status) => [status.role, status]));
  return (
    <Panel className="flex flex-col gap-4 p-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold">Run settings</h2>
        <p className="text-sm text-muted-foreground">
          These models affect scores, so the specification records them. The
          download starts when you continue. Keys stay in <Mono>.env</Mono>.
          Leave a field empty to use the environment. See{" "}
          <Mono>{MODEL_GUIDE}</Mono>.
        </p>
      </div>
      {roles.map((role) => {
        const status = byRole.get(role);
        const id = `run-model-${role}`;
        return (
          <div key={role} className="flex flex-col gap-1">
            <label htmlFor={id} className="text-sm font-medium">
              {status?.label ?? role}
            </label>
            <input
              id={id}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              value={values[role] ?? ""}
              placeholder={placeholderModel(role, statuses, values)}
              disabled={busy}
              onChange={(event) => onChange(role, event.currentTarget.value)}
            />
            <p className="text-xs text-muted-foreground">{ROLE_HELP[role]}</p>
            {status && !status.configured && (
              <p className="text-xs text-muted-foreground">
                Not configured: set {status.missing_vars.join(" or ")} before
                the run.
              </p>
            )}
          </div>
        );
      })}
      <div className="flex items-center gap-2">
        {onBack && (
          <Button disabled={busy} onClick={onBack}>
            ← Back
          </Button>
        )}
        <Button variant="primary" disabled={busy} onClick={onContinue}>
          Continue and download
        </Button>
      </div>
    </Panel>
  );
}
