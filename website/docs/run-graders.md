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
that `simulate` made. Running `evaluate` again on the same folder overwrites the earlier results.

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
- Press Ctrl-C to stop every trial. No `results.json` is written, and the log ends with
  `EVALUATION INTERRUPTED`.

`results.json` lists the results in the same order whatever order the trials finish in.

## When traces are missing

Langfuse can take time to show a trace after your application sends it. METIS waits for
`--langfuse-timeout` seconds, 90 by default:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run> --langfuse-timeout 300
```

Traces from older Langfuse Client SDKs can arrive several minutes late. If you see missing
traces, upgrade the [Langfuse Client SDK](set-up-observability.md#langfuse-client-sdk) in your
application first (Python `langfuse` 4.7.0 or later, JS/TS `@langfuse/*` 5.4.0 or later), and
only then raise the timeout. A longer timeout hides the delay but does not remove it. Also
check the keys in `.env` and the [troubleshooting table](set-up-observability.md#troubleshooting).

`metis engine run` takes the same `--langfuse-timeout` option.

## Outputs

`evaluate` writes `outputs/reports/results.json` in the experiment folder, and the log of the
latest evaluation to `logs/evaluate.log`. A trial that cannot be graded is marked failed with the
reason, and the other trials are still graded.

## Next step

Turn your [results into a report](report.md).
