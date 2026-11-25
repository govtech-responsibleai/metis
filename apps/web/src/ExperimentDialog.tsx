// The dialog that "Start an experiment" opens. The user picks the Specification to run, and the
// dialog shows the result of the `metis doctor` checks on the server. The server sets how many
// trials run at a time.

import {
  Check,
  ChevronDown,
  Minus,
  Play,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { startExperiment } from "./experiment-start";
import {
  api,
  type DoctorCheck,
  type EngineRunAccepted,
  type Specification,
} from "./transport/api";
import { relativeTime } from "./relative-time";
import { Button, cn, Modal, Mono } from "./ui";

export type DoctorLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; checks: DoctorCheck[] };

// A Specification that the dialog offers. A Target has one Specification today, so the list has
// one entry, named after the Target.
export interface SpecificationChoice {
  id: string;
  name: string;
  // Epoch milliseconds.
  savedAt: number;
  specification: Specification;
}

export type StartState =
  | { status: "idle" }
  | { status: "starting" }
  | { status: "failed"; message: string };

const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : String(cause);

export function ExperimentDialog({
  targetId,
  choices,
  onCancel,
  onStarted,
}: {
  targetId: string;
  choices: SpecificationChoice[];
  onCancel: () => void;
  onStarted: (experiment: EngineRunAccepted) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [doctor, setDoctor] = useState<DoctorLoad>({ status: "loading" });
  const [start, setStart] = useState<StartState>({ status: "idle" });
  const [chosen, setChosen] = useState(choices[0]?.id ?? "");
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
      className="max-w-xl gap-5 p-6"
      onCancel={onCancel}
    >
      <ExperimentDialogView
        id={id}
        choices={choices}
        chosen={chosen}
        onChoose={setChosen}
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

// The content of the dialog. `id` names its title for the Modal.
export function ExperimentDialogView({
  id,
  choices,
  chosen,
  onChoose,
  doctor,
  start,
  onCheckAgain,
  onCancel,
  onStart,
}: {
  id: string;
  choices: SpecificationChoice[];
  chosen: string;
  onChoose: (id: string) => void;
  doctor: DoctorLoad;
  start: StartState;
  onCheckAgain: () => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  const choice = choices.find((item) => item.id === chosen);
  const cases = choice ? experimentScope(choice.specification).testCases : 0;
  const failed =
    doctor.status === "ready"
      ? doctor.checks.filter((check) => check.status === "fail").length
      : 0;
  const blocked = !choice
    ? "Choose a Specification first"
    : cases === 0
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
      <h2 id={`${id}-title`} className="text-base font-semibold">
        Start an experiment
      </h2>
      <SpecificationPicker
        choices={choices}
        chosen={choice}
        onChoose={onChoose}
      />
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

export function experimentScope(specification: Specification) {
  return {
    testCases: specification.tasks.length,
    trials: specification.tasks.reduce(
      (total, task) => total + task.num_trials,
      0,
    ),
  };
}

const count = (value: number, one: string, many: string) =>
  `${value} ${value === 1 ? one : many}`;

export function choiceDetail(choice: SpecificationChoice, now = Date.now()) {
  const { testCases, trials } = experimentScope(choice.specification);
  return `${count(testCases, "Test Case", "Test Cases")}, ${count(trials, "trial", "trials")}. Saved ${relativeTime(choice.savedAt, now)}`;
}

function ChoiceText({ choice }: { choice: SpecificationChoice }) {
  return (
    <span className="flex min-w-0 flex-col">
      <span className="truncate text-sm font-medium text-foreground">
        {choice.name}
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {choiceDetail(choice)}
      </span>
    </span>
  );
}

// A dropdown with two lines for each Specification: its name, and its Test Cases, trials and
// save time. A native select shows only one line. The list opens under the control, with the
// chosen entry in focus. The arrow keys move between the entries, and Escape, Tab, or a click
// outside closes it.
function SpecificationPicker({
  choices,
  chosen,
  onChoose,
}: {
  choices: SpecificationChoice[];
  chosen: SpecificationChoice | undefined;
  onChoose: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const labelId = useId();
  const listId = useId();
  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };
  useEffect(() => {
    if (!open) return;
    const options = [
      ...(list.current?.querySelectorAll<HTMLElement>('[role="option"]') ?? []),
    ];
    (
      options.find((option) => option.ariaSelected === "true") ?? options[0]
    )?.focus();
    const outside = (event: Event) => {
      const target = event.target as Node;
      if (list.current?.contains(target) || trigger.current?.contains(target))
        return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  return (
    <div className="relative flex flex-col gap-1">
      <span id={labelId} className="text-sm font-medium">
        Specification
      </span>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-labelledby={labelId}
        disabled={choices.length === 0}
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full min-w-0 items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-left transition-colors duration-150",
          "hover:bg-muted disabled:cursor-not-allowed disabled:opacity-45",
          open && "bg-muted",
        )}
      >
        <span className="min-w-0 flex-1">
          {chosen ? (
            <ChoiceText choice={chosen} />
          ) : (
            <span className="text-sm text-muted-foreground">
              No Specification
            </span>
          )}
        </span>
        <ChevronDown
          size={14}
          strokeWidth={1.75}
          aria-hidden
          className="shrink-0 text-muted-foreground"
        />
      </button>
      {open && (
        <div
          ref={list}
          id={listId}
          role="listbox"
          aria-labelledby={labelId}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              // The dialog closes on Escape, so the list keeps the key to itself.
              event.preventDefault();
              event.stopPropagation();
              close(true);
              return;
            }
            if (event.key === "Tab") {
              close(false);
              return;
            }
            const step =
              event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
            if (step === 0) return;
            event.preventDefault();
            const options = [
              ...(list.current?.querySelectorAll<HTMLElement>(
                '[role="option"]',
              ) ?? []),
            ];
            const index = options.indexOf(
              document.activeElement as HTMLElement,
            );
            options[(index + step + options.length) % options.length]?.focus();
          }}
          className="animate-open-menu absolute inset-x-0 top-full z-10 mt-1 flex max-h-72 flex-col overflow-y-auto rounded-lg border border-border bg-card p-1.5 shadow-lg"
        >
          {choices.map((choice) => {
            const selected = choice.id === chosen?.id;
            return (
              <button
                key={choice.id}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChoose(choice.id);
                  close(true);
                }}
                className={cn(
                  "flex w-full min-w-0 items-center gap-2 rounded-md px-2.5 py-2 text-left outline-none transition-colors duration-150",
                  "hover:bg-muted focus-visible:bg-muted",
                  selected && "bg-accent/8",
                )}
              >
                <span className="min-w-0 flex-1">
                  <ChoiceText choice={choice} />
                </span>
                {selected && (
                  <Check
                    size={14}
                    strokeWidth={2}
                    aria-hidden
                    className="shrink-0 text-foreground"
                  />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
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
