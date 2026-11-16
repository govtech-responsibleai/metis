// The dialog that "Start an experiment" opens. It shows what the experiment covers and the checks
// of `metis doctor` on the server. The server sets how many trials run at a time.

import { Check, Minus, Play, TriangleAlert, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { startExperiment } from "./experiment-start";
import {
  api,
  type DoctorCheck,
  type ExperimentRecord,
  type Specification,
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
  onStarted: (experiment: ExperimentRecord) => void;
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
        onStart={() => {
          setStart({ status: "starting" });
          startExperiment(targetId).then(onStarted, (cause: unknown) =>
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
  onStart: () => void;
}) {
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
        ? "Wait for the server checks"
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
      <ServerChecks
        doctor={doctor}
        failed={failed}
        onCheckAgain={onCheckAgain}
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
          onClick={onStart}
        >
          <Play size={14} strokeWidth={2} aria-hidden />
          Start
        </Button>
      </div>
    </>
  );
}

// When every check passes, the dialog shows one line. It lists only the checks that warn or
// fail, because only those ask the user to do something. Each row gives the check name and the
// reason. The fix text says the name again, so the dialog leaves it out. The rows share the
// columns of the list, so every name starts and every reason ends at the same place.
function ServerChecks({
  doctor,
  failed,
  onCheckAgain,
}: {
  doctor: DoctorLoad;
  failed: number;
  onCheckAgain: () => void;
}) {
  if (doctor.status === "loading")
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Checking the server
      </p>
    );
  if (doctor.status === "failed")
    return (
      <p className="flex items-center justify-between gap-3 text-sm">
        <span role="alert" className="text-destructive">
          {doctor.message}
        </span>
        <Button type="button" onClick={onCheckAgain}>
          Check again
        </Button>
      </p>
    );
  const open = doctor.checks.filter(
    (check) => check.status === "fail" || check.status === "warn",
  );
  if (open.length === 0)
    return (
      <p className="flex items-center gap-1 text-sm text-success">
        <Check size={14} aria-hidden />
        Server ready
      </p>
    );
  return (
    <section className="flex flex-col gap-2" aria-label="Server checks">
      <ul className="quiet-scrollbar grid max-h-[45vh] grid-cols-[1.25rem_auto_minmax(0,1fr)] gap-x-2 overflow-y-auto rounded-md border border-border bg-background px-3 py-1">
        {open.map((check) => (
          <li
            key={check.name}
            className="col-span-3 grid grid-cols-subgrid items-baseline border-b border-border py-1.5 text-sm last:border-b-0"
          >
            <span className="flex h-5 items-center self-start">
              <DoctorIcon status={check.status} />
            </span>
            <Mono className="text-foreground">{check.name}</Mono>
            <span
              className={cn(
                "text-right",
                check.status === "fail" ? "text-fail" : "text-muted-foreground",
              )}
            >
              {check.detail}
            </span>
          </li>
        ))}
      </ul>
      {failed > 0 && (
        <p className="flex items-center justify-between gap-3 text-sm">
          <span>Fix the server, then check again.</span>
          <Button type="button" onClick={onCheckAgain}>
            Check again
          </Button>
        </p>
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
