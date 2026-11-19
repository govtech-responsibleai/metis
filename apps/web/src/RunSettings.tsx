// Model settings in the browser: the start check for the interview role, and the run
// settings step after the last review. The browser never sees a key or a URL. `GET /models`
// returns names and status only, and the run settings step writes model names only.

import type {
  InterviewState,
  ModelRole,
  ModelStatus,
  Specification,
} from "./transport/api";
import { TriangleAlert } from "lucide-react";
import { TextInput } from "./fields";
import { Button, Mono, Panel } from "./ui";

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
    "Acts as the user. Use a model that is different from your target.",
  runner_agent:
    "Acts on the target for the generic runner. Empty uses the user agent model.",
  judge:
    "Scores each Criterion. Use a model family that is different from your target.",
};

// The roles that a run of this Specification calls. The runner agent runs only for a generic
// runner, which a target binding selects.
export function runRoles(specification: Specification): RunModelRole[] {
  return specification.target_binding
    ? ["user_agent", "runner_agent", "judge"]
    : ["user_agent", "judge"];
}

// The runner agent uses the user agent model of the run when `RUNNER_AGENT_MODEL` is not set.
function runnerFollowsUserAgent(statuses: readonly ModelStatus[]): boolean {
  return statuses.some(
    (status) =>
      status.role === "runner_agent" && status.source === "user agent model",
  );
}

// The models that the fields start with, for the roles that the run calls: the model that the
// Specification records, else the model of the environment, so the fields show the models that
// the run uses.
export function filledRunModels(
  specification: Specification,
  statuses: readonly ModelStatus[],
): RunModels {
  const defaults = specification.defaults ?? {};
  const environment = new Map(statuses.map((s) => [s.role, s.model]));
  const models: RunModels = {};
  const roles = runRoles(specification);
  for (const role of roles) {
    const value = defaults[DEFAULT_FIELD[role]] ?? environment.get(role);
    if (value) models[role] = value;
  }
  if (
    roles.includes("runner_agent") &&
    !defaults.runner_agent_model &&
    runnerFollowsUserAgent(statuses)
  )
    models.runner_agent = models.user_agent;
  return models;
}

// One field changes. While the runner agent field holds the user agent model, it follows the
// user agent field, as the run does.
export function withRunModel(
  models: RunModels,
  role: RunModelRole,
  value: string,
  statuses: readonly ModelStatus[],
): RunModels {
  const next = { ...models, [role]: value };
  if (
    role === "user_agent" &&
    runnerFollowsUserAgent(statuses) &&
    models.runner_agent === models.user_agent
  )
    next.runner_agent = value;
  return next;
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

// Whether the Interview can start. Only the interview role is required. The run roles are needed
// only for `metis engine run`.
export function interviewReady(statuses: readonly ModelStatus[]): boolean {
  return !statuses.some(
    (status) => status.role === "interview" && !status.configured,
  );
}

// The Interview on screen and whether it is done.
export type Completion = { id: string; done: boolean };

// The run settings step opens each time the Interview on screen changes from in progress to
// done, on any path. An Interview that opens already done goes to the Done panel.
export function completesNow(
  before: Completion | null,
  after: Completion,
): boolean {
  return before?.id === after.id && !before.done && after.done;
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
    <Panel className="flex flex-col">
      <div className="flex flex-col gap-1 px-5 pt-5">
        <h2 className="text-base font-semibold">Run settings</h2>
        <p className="text-sm text-muted-foreground">
          These models affect scores, so the specification records them. The
          fields start with the models in <Mono>.env</Mono>.
        </p>
      </div>
      <div className="flex flex-col gap-4 px-5 py-5">
        {roles.map((role) => {
          const status = byRole.get(role);
          return (
            <div key={role} className="flex flex-col gap-1.5">
              {/* The label and the help line start where the text in the box starts. */}
              <label
                htmlFor={`run-model-${role}`}
                className="px-3 text-sm font-medium text-foreground"
              >
                {status?.label ?? role}
              </label>
              <TextInput
                id={`run-model-${role}`}
                value={values[role] ?? ""}
                spellCheck={false}
                disabled={busy}
                onChange={(value) => onChange(role, value)}
              />
              <p className="px-3 text-xs text-muted-foreground">
                {ROLE_HELP[role]}
              </p>
              {status && !status.configured && (
                <p className="flex items-center gap-1.5 px-3 text-xs text-warning">
                  <TriangleAlert size={14} aria-hidden />
                  Set {status.missing_vars.join(" or ")} before the run.
                </p>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-4">
        {onBack ? (
          <Button disabled={busy} onClick={onBack}>
            ← Back
          </Button>
        ) : (
          <span />
        )}
        <Button variant="primary" disabled={busy} onClick={onContinue}>
          Continue and download
        </Button>
      </div>
    </Panel>
  );
}
