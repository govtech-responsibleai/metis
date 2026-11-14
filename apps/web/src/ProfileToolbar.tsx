// The toolbar of the Profile pane: Download, and the choice between the Document and the YAML
// of the Specification. Both wait for the end of the Interview.

import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { exportedSpecification } from "./export";
import { LOCKED } from "./TargetPage";
import { api, TransportError, type InterviewState } from "./transport/api";
import { Button, cn } from "./ui";
import { YamlBlock } from "./YamlBlock";

export type ProfileMode = "document" | "yaml";

const MODES: Array<{ id: ProfileMode; label: string }> = [
  { id: "document", label: "Document" },
  { id: "yaml", label: "YAML" },
];

export function ProfileToolbar({
  mode,
  onMode,
  done,
  busy,
  onDownload,
}: {
  mode: ProfileMode;
  onMode: (mode: ProfileMode) => void;
  done: boolean;
  busy: boolean;
  onDownload: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Button
        disabled={!done || busy}
        title={done ? "Download the specification package" : LOCKED}
        onClick={onDownload}
      >
        <Download size={13} strokeWidth={2} aria-hidden />
        Download
      </Button>
      <div
        role="radiogroup"
        aria-label="View"
        className="flex rounded-md border border-border bg-background p-0.5"
      >
        {MODES.map(({ id, label }) => {
          const locked = id === "yaml" && !done;
          return (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={mode === id}
              disabled={locked}
              title={locked ? LOCKED : undefined}
              onClick={() => onMode(id)}
              className={cn(
                "rounded-[6px] px-2.5 py-1 text-sm font-medium transition-colors duration-150",
                mode === id
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
                "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:text-muted-foreground",
              )}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

type Compiled =
  | { status: "loading" }
  | { status: "ready"; text: string }
  | { status: "error"; message: string };

// One compile for each saved Interview state, so a switch between Document and YAML does not
// send the request again.
const compiled = new WeakMap<InterviewState, Promise<string>>();

function compileYaml(state: InterviewState): Promise<string> {
  let request = compiled.get(state);
  if (!request) {
    request = api
      .compile(exportedSpecification(state))
      .then((result) => result["specification.yaml"]);
    request.catch(() => compiled.delete(state));
    compiled.set(state, request);
  }
  return request;
}

export function YamlView({ state }: { state: InterviewState }) {
  const [compiledState, setCompiled] = useState<Compiled>({
    status: "loading",
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    setCompiled({ status: "loading" });
    compileYaml(state).then(
      (text) => {
        if (current) setCompiled({ status: "ready", text });
      },
      (cause: unknown) => {
        if (current)
          setCompiled({
            status: "error",
            message:
              cause instanceof TransportError || cause instanceof Error
                ? cause.message
                : "Something went wrong.",
          });
      },
    );
    return () => {
      current = false;
    };
  }, [state, attempt]);

  if (compiledState.status === "loading")
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Compiling specification.yaml…
      </p>
    );
  if (compiledState.status === "error")
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-3 rounded-lg border border-border bg-card p-5 text-sm"
      >
        <p>The specification could not compile. {compiledState.message}</p>
        <Button onClick={() => setAttempt((value) => value + 1)}>Retry</Button>
      </div>
    );
  return <YamlBlock text={compiledState.text} name="specification.yaml" />;
}
