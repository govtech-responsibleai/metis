// The Trials tab of an Experiment: the progress of its run and one row for each trial. It shows
// no grades. The report has them.

import {
  ChevronDown,
  ChevronRight,
  Circle,
  CircleCheck,
  CirclePause,
  CircleSlash,
  Clock,
  ExternalLink,
  Loader,
  Minus,
  Square,
  X,
} from "lucide-react";
import { useState, type CSSProperties } from "react";
import { Link } from "wouter";
import {
  phaseSteps,
  progressText,
  stepParts,
  type ExperimentState,
  type StepPhase,
} from "./experiment-status";
import { paths } from "./routes";
import { StateBadge } from "./StateBadge";
import {
  statusCounts,
  TRIAL_STATUS_LABEL,
  TRIAL_STATUSES,
  type TrialRow,
  type TrialStatus,
} from "./trials";
import { Button, cn, Mono, Panel, SelectBox, Tooltip } from "./ui";

// The number is the progress of the whole Experiment, so each step is one half of it.
function ExperimentProgress({ state }: { state: ExperimentState }) {
  const parts = stepParts(state);
  const percent = Math.round(((parts.simulate + parts.evaluate) / 2) * 100);
  return (
    <Panel className="flex items-center gap-5 p-5">
      <ProgressRing state={state} percent={percent} />
      <div className="flex flex-1 flex-col gap-3">
        <div className="flex items-baseline gap-3">
          <span className="text-3xl font-semibold tabular-nums">
            {percent}%
          </span>
          <span className="text-sm tabular-nums text-muted-foreground">
            {progressText(state.progress)}
          </span>
        </div>
        <PhaseSteps state={state} />
      </div>
      <StateBadge state={state} plain />
    </Panel>
  );
}

const STEP_STROKE: Record<StepPhase, string> = {
  done: "stroke-success",
  live: "stroke-accent",
  paused: "stroke-skipped",
  next: "stroke-skipped",
};

// The length of one half of the ring, out of 100. The rest of the half is the gap between halves.
const HALF = 47;

// The longest reach of the tail that grows from the end of the fill in the live half.
const REACH = 14;

// The right half of the ring is Simulate and the left half is Evaluate.
function ProgressRing({
  state,
  percent,
}: {
  state: ExperimentState;
  percent: number;
}) {
  const steps = phaseSteps(state);
  const parts = stepParts(state);
  const halves = [
    { key: "simulate", phase: steps.simulate, part: parts.simulate },
    { key: "evaluate", phase: steps.evaluate, part: parts.evaluate },
  ];
  return (
    <svg
      viewBox="0 0 64 64"
      className="h-16 w-16 shrink-0 -rotate-90"
      fill="none"
      strokeWidth={5}
      role="progressbar"
      aria-label="Experiment progress"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
    >
      {halves.map((half, index) => {
        const offset = -(index * 50 + (50 - HALF) / 2);
        const filled = HALF * half.part;
        return (
          <g key={half.key}>
            <circle
              cx={32}
              cy={32}
              r={28}
              pathLength={100}
              className="stroke-muted"
              strokeDasharray={`${HALF} ${100 - HALF}`}
              strokeDashoffset={offset}
            />
            <circle
              cx={32}
              cy={32}
              r={28}
              pathLength={100}
              className={cn(
                "transition-[stroke-dasharray,stroke] duration-300 ease-out",
                STEP_STROKE[half.phase],
              )}
              strokeDasharray={`${filled} ${100 - filled}`}
              strokeDashoffset={offset}
            />
            {half.phase === "live" && filled < HALF && (
              <circle
                cx={32}
                cy={32}
                r={28}
                pathLength={100}
                className="ring-reach stroke-accent"
                strokeDashoffset={offset - filled}
                style={
                  {
                    "--reach": `${Math.min(REACH, HALF - filled)}`,
                  } as CSSProperties
                }
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

const STEP_ICON: Record<StepPhase, typeof Circle> = {
  done: CircleCheck,
  live: Loader,
  paused: CirclePause,
  next: Circle,
};

function PhaseSteps({ state }: { state: ExperimentState }) {
  const steps = phaseSteps(state);
  return (
    <ol className="flex items-center gap-3 text-sm" aria-label="Phases">
      {(
        [
          ["Simulate", steps.simulate],
          ["Evaluate", steps.evaluate],
        ] as const
      ).map(([label, phase], index) => {
        const Icon = STEP_ICON[phase];
        return (
          <li key={label} className="flex items-center gap-3">
            {index > 0 && (
              <ChevronRight
                size={14}
                className="text-muted-foreground"
                aria-hidden
              />
            )}
            <span
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2 py-0.5",
                phase === "live" && "border-accent/40 bg-accent/8 font-medium",
                phase === "done" && "border-success/40 bg-success/8",
                (phase === "next" || phase === "paused") &&
                  "border-border text-muted-foreground",
              )}
              aria-current={phase === "live" ? "step" : undefined}
            >
              <Icon
                size={13}
                className={cn(
                  phase === "live" && "run-turn text-accent",
                  phase === "done" && "text-success",
                )}
                aria-hidden
              />
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// The link repeats on every row, so it is a quiet icon rather than the case drawer's button.
function SessionLink({ url }: { url: string }) {
  const label = "Open in Langfuse";
  return (
    <Tooltip label={label} hoverOnly className="inline-flex">
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={label}
        className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:text-foreground"
      >
        <ExternalLink size={14} strokeWidth={1.75} aria-hidden />
      </a>
    </Tooltip>
  );
}

// A trial that did not run is an app error, so it has the destructive colour. A trial with no
// grade is skipped. A trial that ends a phase has the colour of a done phase, as on the ring.
function TrialIcon({ status }: { status: TrialStatus }) {
  switch (status) {
    case "waiting":
      return <Minus size={14} className="text-skipped" aria-hidden />;
    case "simulating":
    case "grading":
      return <Loader size={14} className="run-turn text-accent" aria-hidden />;
    case "simulated":
      return <Clock size={14} className="text-success" aria-hidden />;
    case "graded":
      return <CircleCheck size={14} className="text-success" aria-hidden />;
    case "failed":
      return <X size={14} className="text-destructive" aria-hidden />;
    case "grading-failed":
      return <CircleSlash size={14} className="text-skipped" aria-hidden />;
    case "stopped":
      return <Square size={12} className="text-muted-foreground" aria-hidden />;
  }
}

const QUIET: ReadonlySet<TrialStatus> = new Set(["waiting", "stopped"]);

function StatusFilter({
  rows,
  value,
  onChange,
}: {
  rows: readonly TrialRow[];
  value: ReadonlySet<TrialStatus>;
  onChange: (value: ReadonlySet<TrialStatus>) => void;
}) {
  const [open, setOpen] = useState(false);
  const counts = statusCounts(rows);
  const shown = TRIAL_STATUSES.filter((status) => counts[status] > 0);
  const all = shown.every((status) => value.has(status));
  const toggle = (status: TrialStatus) => {
    const next = new Set(value);
    if (next.has(status)) next.delete(status);
    else next.add(status);
    onChange(next);
  };
  return (
    <div className="relative">
      <Button onClick={() => setOpen(!open)} aria-expanded={open} active={!all}>
        <span className="text-muted-foreground">Status</span>
        <span>{all ? "All" : "Some"}</span>
        <ChevronDown
          size={14}
          aria-hidden
          className={cn(
            "transition-transform duration-150",
            open && "rotate-180",
          )}
        />
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 flex w-60 flex-col gap-0.5 rounded-lg border border-border bg-card p-2 shadow-lg">
            {shown.map((status) => {
              const id = `trial-status-${status}`;
              return (
                <label
                  key={status}
                  htmlFor={id}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                >
                  <SelectBox
                    id={id}
                    label={TRIAL_STATUS_LABEL[status]}
                    checked={value.has(status)}
                    onChange={() => toggle(status)}
                  />
                  <TrialIcon status={status} />
                  <span className="flex-1">{TRIAL_STATUS_LABEL[status]}</span>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {counts[status]}
                  </span>
                </label>
              );
            })}
            <button
              type="button"
              className="mt-1 border-t border-border px-1 pt-2 text-left text-sm text-muted-foreground hover:text-foreground"
              onClick={() => onChange(new Set(TRIAL_STATUSES))}
            >
              Select all
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function TrialsTab({
  targetId,
  experimentId,
  state,
  rows,
  taskId,
}: {
  targetId: string;
  experimentId: string;
  state: ExperimentState;
  rows: readonly TrialRow[];
  // The Test Case that the URL names, or null for every trial.
  taskId: string | null;
}) {
  const [statuses, setStatuses] = useState<ReadonlySet<TrialStatus>>(
    new Set(TRIAL_STATUSES),
  );
  const ofCase =
    taskId === null ? rows : rows.filter((row) => row.taskId === taskId);
  const shown = ofCase.filter((row) => statuses.has(row.status));
  return (
    <>
      <ExperimentProgress state={state} />
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 className="flex items-baseline gap-2 text-base font-semibold">
            Trials
            {taskId !== null && (
              <>
                <Mono>{taskId}</Mono>
                <Link
                  href={paths.experiment(targetId, experimentId, "trials")}
                  className="text-sm font-normal text-muted-foreground hover:text-foreground"
                >
                  Show all trials
                </Link>
              </>
            )}
          </h2>
          <StatusFilter rows={ofCase} value={statuses} onChange={setStatuses} />
        </div>
        <Panel className="overflow-hidden">
          <table className="w-full table-fixed text-sm">
            <colgroup>
              <col className="w-[6.5rem]" />
              <col className="w-[3.5rem]" />
              <col className="w-[27%]" />
              <col className="w-[29%]" />
              <col className="w-[9rem]" />
              <col />
              <col className="w-[2.5rem]" />
            </colgroup>
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-muted-foreground">
                <th className="px-4 py-2.5 font-medium">Test Case</th>
                <th className="px-2 py-2.5 font-medium">Trial</th>
                <th className="px-2 py-2.5 font-medium">Persona</th>
                <th className="px-2 py-2.5 font-medium">Scenario</th>
                <th className="px-2 py-2.5 font-medium">Status</th>
                <th className="px-2 py-2.5 font-medium">Reason</th>
                <th className="py-2.5" />
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr
                  key={row.trial}
                  className="border-b border-border last:border-b-0"
                >
                  <td className="px-4 py-2.5 break-all">
                    <span className="font-mono text-xs tracking-tight">
                      {row.taskId ?? row.trial}
                    </span>
                  </td>
                  <td className="px-2 py-2.5 font-mono text-xs tabular-nums">
                    {row.index}
                  </td>
                  <td className="truncate px-2 py-2.5">{row.persona}</td>
                  <td className="truncate px-2 py-2.5">{row.scenario}</td>
                  <td className="px-2 py-2.5">
                    <span className="flex items-center gap-2">
                      <TrialIcon status={row.status} />
                      <span
                        className={cn(
                          QUIET.has(row.status) && "text-muted-foreground",
                        )}
                      >
                        {TRIAL_STATUS_LABEL[row.status]}
                      </span>
                    </span>
                  </td>
                  <td className="px-2 py-2.5 break-words">{row.reason}</td>
                  <td className="pr-2 py-1.5">
                    {row.sessionUrl && <SessionLink url={row.sessionUrl} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <p className="px-4 py-3 text-sm text-muted-foreground">
              {ofCase.length === 0
                ? "The engine has not planned the trials yet."
                : "No trials have the selected status."}
            </p>
          )}
        </Panel>
      </section>
    </>
  );
}
