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

`evaluate` writes `outputs/reports/results.json` in the experiment folder, and the log of the
latest evaluation to `logs/evaluate.log`. A trial that cannot be graded is marked failed with the
reason, and the other trials are still graded.

## Next step

Turn your [results into a report](report.md).
