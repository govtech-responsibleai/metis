---
title: Run the graders
---

`metis engine evaluate` reads each trial's conversation from Langfuse, runs the graders from your
specification and writes the results. It needs the `LANGFUSE_*` and `OPENAI_API_KEY` values in
`.env`, and an application that records its traces as described in
[Set up observability](set-up-observability.md).

## What the graders judge

The graders read each conversation from your application's traces in Langfuse: the messages,
the tool calls and their results. A grader can also judge a file that your application made, such
as an image, a chart or a PDF.

Each grader has settings that choose what it judges, such as one turn, the whole session or one
file. See [How graders work](library/how-graders-work.md) for these settings, and the
[Grader library](library/grader-library.md) for each grader.

## Run it

Pass the output folder that `simulate` created:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run>
```

`simulate` prints this command with your path. The folder must hold the frozen `inputs/` copy
that `simulate` made. Running `evaluate` again on the same folder starts over: once the setup
checks pass, it deletes the earlier evaluation and grades every trial. `logs/events.jsonl` is kept.

## Resume a stopped evaluation

If an evaluation stops before all trials are graded, continue the same folder:

```bash
metis engine evaluate --resume --experiment-dir experiments/execute/<your-run>
```

Resume skips every trial that is already evaluated, grades the rest, and prints
`resuming: K of N trials already evaluated`. A trial is evaluated once it was graded or failed,
for example when it had no session id or Langfuse had no traces for it.

Resume does not retry failed trials or criteria that errored. To grade every trial again, run a
fresh `evaluate`, which deletes the earlier evaluation outputs. The summary prints that command
when any trial failed.

If `results.json` already exists, the evaluation is finished: resume prints `nothing to resume`
and changes nothing.

## Grade several trials at once

By default `evaluate` grades one trial at a time. `--concurrency` (short `-c`) sets how many
trials are graded together:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run> --concurrency 4
```

The number must be at least 1. A new trial starts as soon as any running trial finishes. Raise
it as far as your Langfuse server and your model provider allow. METIS never sends more than 50
grader model calls at once, however large the number is, so a high value makes calls wait
instead of flooding the provider.

With more than one trial at a time, the output changes in four ways:

- The `SESSION i/total` banner for each trial is not printed.
- The progress bar reads `Evaluation — K running`, where K is the number of trials being graded.
  The steps of each trial are in `logs/evaluate.log`.
- Each warning starts with `RECORD i/total` and the trial's persona and scenario.
- Press Ctrl-C to stop every trial. The trials that finished are saved, no `results.json` is
  written, and the log ends with `EVALUATION INTERRUPTED`. The message gives the
  `evaluate --resume` command to continue. Trials still running are lost: at most the number
  you passed to `--concurrency`.

`results.json` lists the results in the same order whatever order the trials finish in.

## When traces are missing

To grade a trial, METIS needs to know when its traces are ready. Langfuse can take time to store
them, so METIS waits before it grades the trial. Two settings control this wait.

The **quiet window** is how long Langfuse must store nothing new for the trial. After the quiet
window, METIS treats the traces as complete and grades them. The default is 30 seconds. Set it in
`.env`:

```bash
LANGFUSE_METIS_QUIET_SECONDS=60
```

The **timeout** is the longest time that METIS waits for each trial. If the traces are not ready
when the timeout ends, the trial fails. The default is 90 seconds. Set it with
`--langfuse-timeout`.

The timeout must be at least as long as the quiet window. A trial that has just finished needs the
full quiet window before METIS can grade it:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run> --langfuse-timeout 300
```

If the traces are not ready in time, the trial fails with one of these reasons:

- `no traces in Langfuse`: Langfuse returned no trace for the trial.
- `traces still changing in Langfuse`: Langfuse kept storing new data until the time was up.

Older Langfuse Client SDKs can send traces several minutes late. Upgrade the
[Langfuse Client SDK](set-up-observability.md#langfuse-client-sdk) first (Python `langfuse` 4.7.0
or later, JS/TS `@langfuse/*` 5.4.0 or later), and only then raise the timeout. Also check the
keys in `.env` and the [troubleshooting table](set-up-observability.md#troubleshooting).

`metis engine run` takes the same `--langfuse-timeout` option.

## Outputs

`evaluate` writes `outputs/reports/results.json` in the experiment folder, and the log to
`logs/evaluate.log`. A trial that cannot be graded is marked failed with the reason, and the other
trials are still graded.

`outputs/evaluation/` holds one file per trial, written when that trial's evaluation ends. These
files are private to METIS; `results.json` is the file to read. METIS writes `results.json` last,
from every trial's file, and only once every trial was attempted, even if every trial failed.
Its presence means the evaluation is finished.

The grading time in the report, and `latency_seconds` and `timings.evaluation_seconds` in
`results.json`, count the time during which at least one trial was being graded. Trials that
overlap count once, and the pause between an interrupted evaluation and its resume counts zero.

## Next step

Turn your [results into a report](report.md).
