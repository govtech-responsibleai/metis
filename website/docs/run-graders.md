---
title: Run the graders
---

`metis engine evaluate` reads each trial's conversation from Langfuse, runs the graders from your
specification and writes the results. It needs the `LANGFUSE_*` and `OPENAI_API_KEY` values in
`.env`, and an application that records its traces as described in
[Make your application eval-friendly](make-app-eval-friendly.md).

## Run it

Pass the output folder that `simulate` created:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run>
```

`simulate` prints this command with your path. The folder must hold the frozen `inputs/` copy
that `simulate` made. Running `evaluate` again on the same folder overwrites the earlier results.

## When traces are missing

Langfuse can take time to show a trace after your application sends it. METIS waits for
`--langfuse-timeout` seconds, 90 by default:

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run> --langfuse-timeout 300
```

Traces from older SDKs can arrive several minutes late. If you see missing traces, upgrade the
application's SDK first (Python `langfuse` 4.7.0 or later, JS/TS `@langfuse/*` 5.4.0 or later),
and only then raise the timeout. A longer timeout hides the delay but does not remove it. Also
check the keys in `.env` and the [troubleshooting table](make-app-eval-friendly.md#troubleshooting).

`metis engine run` takes the same `--langfuse-timeout` option.

## Where the results go

`evaluate` writes `outputs/reports/results.json` in the experiment folder, and the log of the
latest evaluation to `logs/evaluate.log`. A trial that cannot be graded is marked failed with the
reason, and the other trials are still graded.

## Next step

Turn the results into a report:

```bash
metis insights report --results-file experiments/execute/<your-run>/outputs/reports/results.json
```

`evaluate` prints this command with your path. See [Read your report](report.md).
