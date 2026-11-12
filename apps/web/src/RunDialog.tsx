// The dialog that "Start a run" opens. It shows what the run covers and holds the run options.
// Start opens the experiment view.

import { Play } from "lucide-react";
import { useId, useState } from "react";
import { Button, formatTrials, Modal } from "./ui";
import type { Specification } from "./transport/api";

export interface RunOptions {
  // The number of trials that run at one time.
  concurrency: number;
  // The time to wait for the traces of a trial, in seconds.
  traceWait: number;
}

export const DEFAULT_RUN_OPTIONS: RunOptions = {
  concurrency: 1,
  traceWait: 90,
};

export function RunDialog({
  title,
  specification,
  onCancel,
  onStart,
}: {
  title: string;
  // The Specification that the run uses, which is the one that the download exports.
  specification: Specification;
  onCancel: () => void;
  onStart: (options: RunOptions) => void;
}) {
  const id = useId();
  const [options, setOptions] = useState(DEFAULT_RUN_OPTIONS);
  const cases = specification.tasks.length;
  const trials = specification.tasks.reduce(
    (total, task) => total + task.num_trials,
    0,
  );
  return (
    <Modal
      labelledBy={`${id}-title`}
      describedBy={`${id}-scope`}
      className="max-w-md gap-5 p-6"
      onCancel={onCancel}
    >
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="text-base font-semibold">
          Start a run
        </h2>
        <p id={`${id}-scope`} className="text-sm text-muted-foreground">
          {title} has {cases} {cases === 1 ? "Test Case" : "Test Cases"} and{" "}
          {formatTrials(trials)}.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <NumberField
          label="Trials at a time"
          value={options.concurrency}
          min={1}
          max={16}
          onChange={(concurrency) => setOptions({ ...options, concurrency })}
        />
        <NumberField
          label="Trace wait (s)"
          value={options.traceWait}
          min={10}
          max={600}
          onChange={(traceWait) => setOptions({ ...options, traceWait })}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          autoFocus
          disabled={cases === 0}
          title={cases === 0 ? "Select a Test Case first" : undefined}
          onClick={() => onStart(options)}
        >
          <Play size={14} strokeWidth={2} aria-hidden />
          Start
        </Button>
      </div>
    </Modal>
  );
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
    <div className="flex flex-col gap-1">
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
