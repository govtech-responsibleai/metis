// The mode picker and the target connection form. In the opening the form is the panel under the
// box when the user chooses "Build Spec and connect target". The manual form shows it as a card
// in run mode. The Done pane shows it again to add a connection later.
// Secret fields take environment-variable names only.
import { ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { ConnectionCheckResult } from "./transport/api";
import {
  errorsByField,
  submissionHints,
  type ConnectionDraft,
  type ConnectionMode,
} from "./connection";
import { Button, cn } from "./ui";

const MODE_LABELS: Record<ConnectionMode, string> = {
  spec: "Build Spec only",
  run: "Build Spec and connect target",
};

// The mode is a choice about the whole session. In the opening it sits above the box, apart from
// the chips that give the Interview its context. The manual form shows it in its header.
export function ModePicker({
  mode,
  disabled,
  onSelect,
}: {
  mode: ConnectionMode;
  disabled: boolean;
  onSelect: (mode: ConnectionMode) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Mode"
      // The selected option's corners follow the border: its radius is the outer radius less
      // the padding (16px - 2px).
      className="inline-flex self-center rounded-lg border border-border bg-card p-0.5"
    >
      {(["spec", "run"] as const).map((id) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={mode === id}
          disabled={disabled}
          onClick={() => onSelect(id)}
          className={cn(
            "rounded-[14px] px-3.5 py-1.5 text-sm transition-colors duration-150",
            mode === id
              ? "bg-accent/10 font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground",
            "disabled:cursor-not-allowed disabled:opacity-45",
          )}
        >
          {MODE_LABELS[id]}
        </button>
      ))}
    </div>
  );
}

const SECRET_HINT = "Variable name only. Set its value in .env.";

export function ConnectionForm({
  draft,
  onDraft,
  result,
  busy,
  onTest,
}: {
  draft: ConnectionDraft;
  onDraft: (draft: ConnectionDraft) => void;
  result: ConnectionCheckResult | null;
  busy: boolean;
  // Tests the binding now. Send also tests it when no result is current.
  onTest: () => void;
}) {
  const [more, setMore] = useState(false);
  const errors = errorsByField(draft, result);
  const hints = submissionHints(draft, result);
  const set = <K extends keyof ConnectionDraft>(
    key: K,
    value: ConnectionDraft[K],
  ) => onDraft({ ...draft, [key]: value });
  const http = draft.transport === "http";
  // An error, a warning, or a suggestion for a field under "More options" opens it, so the
  // user sees it.
  const moreError = http
    ? errors.secretHeaders ||
      errors.forbiddenCalls ||
      errors.submissions ||
      errors.notes ||
      hints.warning ||
      hints.suggestion.length > 0
    : errors.loginSecrets || errors.notes;

  // TODO: Link the target connection setup guide here when the docs are ready. The fields are
  // hard to fill in without it.
  return (
    <div className="flex flex-col gap-4">
      <Toggle
        label="How METIS reaches the target"
        value={draft.transport}
        disabled={busy}
        options={[
          { id: "http", label: "HTTP API" },
          { id: "browser", label: "Browser" },
        ]}
        onChange={(transport) => set("transport", transport)}
      />
      <div className="grid gap-3 sm:grid-cols-[9rem_1fr] sm:items-start">
        <Field
          label="Target name"
          placeholder="Billing bot"
          value={draft.name}
          error={errors.name}
          disabled={busy}
          onChange={(value) => set("name", value)}
        />
        {http ? (
          <>
            <Field
              label="OpenAPI URL"
              placeholder="${APP_URL}/openapi.json"
              value={draft.specUrl}
              error={errors.specUrl}
              disabled={busy}
              onChange={(value) => set("specUrl", value)}
            />
            <Field
              label="API key variable"
              placeholder="APP_API_KEY"
              hint={SECRET_HINT}
              value={draft.secretEnv}
              error={errors.secretEnv}
              disabled={busy}
              onChange={(value) => set("secretEnv", value)}
            />
          </>
        ) : (
          <>
            <Field
              label="Start page URL"
              placeholder="${APP_URL}/login"
              value={draft.startUrl}
              error={errors.startUrl}
              disabled={busy}
              onChange={(value) => set("startUrl", value)}
            />
            <Field
              multiline
              label="Sign-in steps"
              placeholder="Type {{secret:APP_USER}} in the email box and {{secret:APP_PASSWORD}} in the password box."
              hint="Write {{secret:NAME}} where a secret is typed."
              value={draft.loginNote}
              error={errors.loginNote}
              disabled={busy}
              onChange={(value) => set("loginNote", value)}
            />
          </>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <button
          type="button"
          aria-expanded={more || !!moreError}
          onClick={() => setMore(!more)}
          className="flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronRight
            size={14}
            strokeWidth={1.75}
            aria-hidden
            className={cn(
              "transition-transform duration-150",
              (more || moreError) && "rotate-90",
            )}
          />
          More options
        </button>
        {(more || moreError) && (
          <div className="grid gap-3 sm:grid-cols-[9rem_1fr] sm:items-start">
            {http ? (
              <>
                <Field
                  multiline
                  label="Secret headers"
                  placeholder="POST /chat X-Api-Key APP_HEADER_KEY"
                  hint="One per line: METHOD /path HEADER VARIABLE."
                  value={draft.secretHeaders}
                  error={errors.secretHeaders}
                  disabled={busy}
                  onChange={(value) => set("secretHeaders", value)}
                />
                <Field
                  multiline
                  label="Refused calls"
                  placeholder="DELETE /**"
                  hint="One per line. The Engine never sends these."
                  value={draft.forbiddenCalls}
                  error={errors.forbiddenCalls}
                  disabled={busy}
                  onChange={(value) => set("forbiddenCalls", value)}
                />
                <Field
                  multiline
                  label="Submissions"
                  placeholder="POST /chat"
                  hint="One per line. The calls that send the user's message."
                  value={draft.submissions}
                  error={errors.submissions}
                  warning={hints.warning ?? undefined}
                  disabled={busy}
                  onChange={(value) => set("submissions", value)}
                />
                {hints.suggestion.length > 0 && (
                  <>
                    <span aria-hidden className="max-sm:hidden" />
                    <div className="flex flex-col items-start gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
                      <p className="text-foreground">
                        The OpenAPI document suggests these submissions. Check
                        them before you use them.
                      </p>
                      <ul className="flex flex-col gap-0.5">
                        {hints.suggestion.map((pattern) => (
                          <li key={pattern}>
                            <code>{pattern}</code>
                          </li>
                        ))}
                      </ul>
                      <Button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          set("submissions", hints.suggestion.join("\n"))
                        }
                      >
                        Use these submissions
                      </Button>
                    </div>
                  </>
                )}
                <span aria-hidden className="max-sm:hidden" />
                <label className="flex items-center gap-2 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={draft.tlsVerify}
                    disabled={busy}
                    onChange={(event) => set("tlsVerify", event.target.checked)}
                  />
                  Verify the TLS certificate
                </label>
              </>
            ) : (
              <Field
                label="Sign-in variables"
                placeholder="APP_USER, APP_PASSWORD"
                hint={SECRET_HINT}
                value={draft.loginSecrets}
                error={errors.loginSecrets}
                disabled={busy}
                onChange={(value) => set("loginSecrets", value)}
              />
            )}
            <Field
              multiline
              label="Runner notes"
              placeholder="The chat replies after a few seconds."
              hint="Advice for the runner agent."
              value={draft.notes}
              error={errors.notes}
              disabled={busy}
              onChange={(value) => set("notes", value)}
            />
          </div>
        )}
      </div>
      {errors.binding && (
        <p className="text-sm text-destructive">{errors.binding}</p>
      )}
      <ConnectionStatusLine result={result} />
      <Button
        type="button"
        className="self-end"
        disabled={busy}
        onClick={onTest}
      >
        Test connection
      </Button>
    </div>
  );
}

export function ConnectionStatusLine({
  result,
}: {
  result: ConnectionCheckResult | null;
}) {
  if (!result) return null;
  if (!result.binding)
    return (
      <p role="status" className="text-sm text-destructive">
        Fix the marked fields, or choose Build Spec only.
      </p>
    );
  // A failed check shows under the field it belongs to, so the list keeps the passed ones.
  const failed = (result.probes ?? []).some((probe) => !probe.ok);
  return (
    <ul role="status" className="flex flex-col gap-1 text-sm">
      <li className="text-foreground">✓ The fields are valid.</li>
      {(result.probes ?? [])
        .filter((probe) => probe.ok)
        .map((probe) => (
          <li key={probe.name} className="text-foreground">
            ✓ <code>{probe.name}</code>: {probe.message}
          </li>
        ))}
      {failed && (
        <li className="text-destructive">
          ✗ Some checks failed. Fix the marked fields and test again.
        </li>
      )}
      {!result.live && (
        <li className="text-muted-foreground">
          This server checks the fields only. Run{" "}
          <code>metis wizard connect</code> to test the connection.
        </li>
      )}
    </ul>
  );
}

function Toggle<T extends string>({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: T;
  options: Array<{ id: T; label: string }>;
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex self-start rounded-md border border-border p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          disabled={disabled}
          onClick={() => onChange(option.id)}
          className={cn(
            "rounded-[5px] px-3 py-1 text-sm transition-colors duration-150",
            value === option.id
              ? "bg-accent/10 font-medium text-foreground"
              : "text-muted-foreground hover:text-foreground",
            "disabled:cursor-not-allowed disabled:opacity-45",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// One labelled field. On a wide screen the label sits in the left column of the form grid.
function Field({
  label,
  value,
  placeholder,
  hint,
  error,
  warning,
  disabled,
  multiline = false,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  hint?: string;
  error?: string;
  // A problem that does not stop the binding, such as a pattern that matches no call.
  warning?: string;
  disabled: boolean;
  multiline?: boolean;
  onChange: (value: string) => void;
}): ReactNode {
  const className =
    "w-full rounded-md border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground aria-[invalid=true]:border-destructive";
  return (
    <label className="contents">
      <span className="text-sm text-foreground sm:pt-2">{label}</span>
      <span className="flex min-w-0 flex-col gap-1">
        {multiline ? (
          <textarea
            aria-invalid={!!error}
            value={value}
            placeholder={placeholder}
            disabled={disabled}
            spellCheck={false}
            onChange={(event) => onChange(event.target.value)}
            className={cn(className, "min-h-16 resize-y py-2")}
          />
        ) : (
          <input
            aria-invalid={!!error}
            value={value}
            placeholder={placeholder}
            disabled={disabled}
            spellCheck={false}
            autoComplete="off"
            onChange={(event) => onChange(event.target.value)}
            className={cn(className, "h-9")}
          />
        )}
        {error ? (
          <span className="text-xs text-destructive">{error}</span>
        ) : warning ? (
          <span className="text-xs text-foreground">⚠ {warning}</span>
        ) : (
          // A hint is a quiet aside, so it is small and sits at the right edge.
          hint && (
            <span className="self-end text-[11px] text-muted-foreground/70">
              {hint}
            </span>
          )
        )}
      </span>
    </label>
  );
}
