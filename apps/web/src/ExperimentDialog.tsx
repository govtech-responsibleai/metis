// The dialog that "Start an experiment" opens. It shows what the experiment covers, the checks of
// `metis doctor` on the server, and the number of trials at a time.

import { Check, Minus, Play, TriangleAlert, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import {
  api,
  store,
  type DoctorCheck,
  type Specification,
  type StartedExperiment,
} from "./transport/api";
import { Button, cn, formatTrials, Modal, Mono } from "./ui";

export type DoctorLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; checks: DoctorCheck[] };

export type StartState =
  | { status: "idle" }
  | { status: "starting" }
  | { status: "failed"; message: string };

const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : String(cause);

export function ExperimentDialog({
  targetId,
  title,
  specification,
  onCancel,
  onStarted,
}: {
  targetId: string;
  title: string;
  // The Specification that the experiment uses, which is the one that the download exports.
  specification: Specification;
  onCancel: () => void;
  onStarted: (experiment: StartedExperiment) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [doctor, setDoctor] = useState<DoctorLoad>({ status: "loading" });
  const [start, setStart] = useState<StartState>({ status: "idle" });
  useEffect(() => {
    let current = true;
    setDoctor({ status: "loading" });
    void api.doctor().then(
      (checks) => {
        if (current) setDoctor({ status: "ready", checks });
      },
      (cause: unknown) => {
        if (current) setDoctor({ status: "failed", message: message(cause) });
      },
    );
    return () => {
      current = false;
    };
  }, [attempt]);
  const id = useId();
  return (
    <Modal
      labelledBy={`${id}-title`}
      describedBy={`${id}-scope`}
      className="max-w-xl gap-5 p-6"
      onCancel={onCancel}
    >
      <ExperimentDialogView
        id={id}
        title={title}
        specification={specification}
        doctor={doctor}
        start={start}
        onCheckAgain={() => setAttempt((count) => count + 1)}
        onCancel={onCancel}
        onStart={(concurrency) => {
          setStart({ status: "starting" });
          store
            .startExperiment(targetId, { concurrency })
            .then(onStarted, (cause: unknown) =>
              setStart({ status: "failed", message: message(cause) }),
            );
        }}
      />
    </Modal>
  );
}

// The content of the dialog. `id` names its title and its scope for the Modal.
export function ExperimentDialogView({
  id,
  title,
  specification,
  doctor,
  start,
  onCheckAgain,
  onCancel,
  onStart,
}: {
  id: string;
  title: string;
  specification: Specification;
  doctor: DoctorLoad;
  start: StartState;
  onCheckAgain: () => void;
  onCancel: () => void;
  onStart: (concurrency: number) => void;
}) {
  const [concurrency, setConcurrency] = useState(1);
  const cases = specification.tasks.length;
  const trials = specification.tasks.reduce(
    (total, task) => total + task.num_trials,
    0,
  );
  const failed =
    doctor.status === "ready"
      ? doctor.checks.filter((check) => check.status === "fail").length
      : 0;
  const blocked =
    cases === 0
      ? "Select a Test Case first"
      : doctor.status === "loading"
        ? "Wait for the checks"
        : failed > 0
          ? "Fix the failed check first"
          : start.status === "starting"
            ? "Starting the experiment"
            : null;
  return (
    <>
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="text-base font-semibold">
          Start an experiment
        </h2>
        <p id={`${id}-scope`} className="text-sm text-muted-foreground">
          {title} has {cases} {cases === 1 ? "Test Case" : "Test Cases"} and{" "}
          {formatTrials(trials)}.
        </p>
      </div>
      <Environment
        doctor={doctor}
        failed={failed}
        onCheckAgain={onCheckAgain}
      />
      <NumberField
        label="Trials at a time"
        value={concurrency}
        min={1}
        max={16}
        onChange={setConcurrency}
      />
      {start.status === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {start.message}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          autoFocus
          disabled={blocked !== null}
          title={blocked ?? undefined}
          onClick={() => onStart(concurrency)}
        >
          <Play size={14} strokeWidth={2} aria-hidden />
          Start
        </Button>
      </div>
    </>
  );
}

function Environment({
  doctor,
  failed,
  onCheckAgain,
}: {
  doctor: DoctorLoad;
  failed: number;
  onCheckAgain: () => void;
}) {
  return (
    <section className="flex flex-col gap-2" aria-label="Environment">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Environment</h3>
        {doctor.status === "ready" &&
          (failed === 0 ? (
            <span className="flex items-center gap-1 text-sm text-success">
              <Check size={14} aria-hidden />
              Ready
            </span>
          ) : (
            <span className="flex items-center gap-1 text-sm text-fail">
              <X size={14} aria-hidden />
              {failed === 1 ? "1 check failed" : `${failed} checks failed`}
            </span>
          ))}
      </div>
      {doctor.status === "loading" ? (
        <p role="status" className="text-sm text-muted-foreground">
          Checking the environment
        </p>
      ) : doctor.status === "failed" ? (
        <p className="flex items-center justify-between gap-3 text-sm">
          <span role="alert" className="text-destructive">
            {doctor.message}
          </span>
          <Button type="button" onClick={onCheckAgain}>
            Check again
          </Button>
        </p>
      ) : (
        <>
          <ul className="quiet-scrollbar flex max-h-[45vh] flex-col overflow-y-auto rounded-md border border-border bg-background px-3 py-1">
            {doctor.checks.map((check) => (
              <li
                key={check.name}
                className="flex flex-col gap-0.5 border-b border-border py-1.5 text-sm last:border-b-0"
              >
                <span className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-2">
                  <DoctorIcon status={check.status} />
                  <Mono className="truncate text-foreground">{check.name}</Mono>
                  <span
                    className={cn(
                      "text-right",
                      check.status === "fail"
                        ? "text-fail"
                        : "text-muted-foreground",
                    )}
                  >
                    {check.detail}
                  </span>
                </span>
                {check.fix && check.status !== "pass" && (
                  <span className="pl-7 text-muted-foreground">
                    {check.fix}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {failed > 0 && (
            <p className="flex items-center justify-between gap-3 text-sm">
              <span>Fix the environment on the server, then check again.</span>
              <Button type="button" onClick={onCheckAgain}>
                Check again
              </Button>
            </p>
          )}
        </>
      )}
    </section>
  );
}

function DoctorIcon({ status }: { status: DoctorCheck["status"] }) {
  switch (status) {
    case "pass":
      return <Check size={14} className="text-success" aria-label="Pass" />;
    case "fail":
      return <X size={14} className="text-fail" aria-label="Fail" />;
    case "warn":
      return (
        <TriangleAlert size={14} className="text-warning" aria-label="Warn" />
      );
    case "skip":
      return <Minus size={14} className="text-skipped" aria-label="Skip" />;
  }
}

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  const id = useId();
  return (
    <div className="flex w-40 flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) =>
          onChange(
            Math.min(
              max,
              Math.max(
                min,
                Math.round(Number(event.currentTarget.value)) || min,
              ),
            ),
          )
        }
        className="rounded-md border border-border bg-background px-3 py-1.5 font-mono text-sm tabular-nums"
      />
    </div>
  );
}
