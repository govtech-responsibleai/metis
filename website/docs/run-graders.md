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

Langfuse can take time to show a trace after your application sends it, and a trace can still
change while Langfuse stores the rest of it. So METIS checks each trial's traces again and again,
with a longer pause each time. It grades the trial when two checks in a row see the same traces,
no trace is empty, and no step in a trace is still open. METIS keeps checking for up to
`--langfuse-timeout` seconds, 90 by default:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run> --langfuse-timeout 300
```

Traces from older Langfuse Client SDKs can arrive several minutes late, which is longer than the
default timeout. A trial can then fail even though its traces would be complete a little later.
If you see missing traces, upgrade the [Langfuse Client SDK](set-up-observability.md#langfuse-client-sdk) in your
application first (Python `langfuse` 4.7.0 or later, JS/TS `@langfuse/*` 5.4.0 or later), and
only then raise the timeout. A longer timeout hides the delay but does not remove it. Also
check the keys in `.env` and the [troubleshooting table](set-up-observability.md#troubleshooting).

If the traces are not ready when the time is up, the trial fails and gets no grades. Two
matching checks make it unlikely that METIS grades part of a conversation, but they cannot rule
it out: if Langfuse pauses for longer than the gap between two checks, a late trace can still be
missed. The reason for a failure is one of these:

- `no traces in Langfuse`: Langfuse returned no trace for the trial.
- `traces still changing in Langfuse`: traces arrived, but they did not stop changing, or a step
  in a trace was never ended. If a longer timeout does not help, check that your application ends
  every step that it starts.

`metis engine run` takes the same `--langfuse-timeout` option.

## Outputs

`evaluate` writes `outputs/reports/results.json` in the experiment folder, and the log of the
latest evaluation to `logs/evaluate.log`. A trial that cannot be graded is marked failed with the
reason, and the other trials are still graded.

## Next step

Turn your [results into a report](report.md).
