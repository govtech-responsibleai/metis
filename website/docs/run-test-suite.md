---
title: Run the test suite
---

`metis engine simulate` runs your test cases against your application. For each trial, a
simulated user talks to the application through the runner, and METIS records the result.
It does not grade anything. METIS must first be able to reach your application. See
[Expose an API or web UI](expose-an-api-or-web-ui.md).

## Start a run

```bash
metis engine simulate --input-dir my-evaluation
```

`--input-dir` is the folder with `specification.yaml`, the target connection that
`target_binding:` names, and `fixtures/`. See [Run your evaluations](run-evaluation.md).

When it finishes, the command prints the output folder, the `evaluate` command for it, and the
`--resume` command. Copy them from the output instead of typing the timestamp.

## Run trials in parallel

```bash
metis engine simulate --input-dir my-evaluation --concurrency 4
```

`--concurrency` (short `-c`) sets how many trials run at once. The default is `1`. Raise it only
as far as your application can handle, and check any rate limits in your target connection.

## Resume a stopped run

If a run stops before all trials finish, continue the same output folder:

```bash
metis engine simulate --resume --experiment-dir experiments/execute/<your-run>
```

Give both flags together. Resume reads the specification from the frozen `inputs/` folder in that
output folder, not from your source folder, and it retries only the trials that are missing or
failed with a system error. Do not combine `--resume` with `--input-dir`.

## Simulate and evaluate together

`metis engine run` does both steps, and also takes `--resume --experiment-dir`:

```bash
metis engine run --input-dir my-evaluation
metis engine run --resume --experiment-dir experiments/execute/<your-run>
```

## Other options

| Option | Meaning |
|---|---|
| `--no-tui` | Print plain log lines instead of the progress screen |
| `--verbose`, `-v` | Show more log detail. Repeat it for more |
| `--quiet` | Show errors only |
| `--log-format` | `text` (default) or `json` for the log files |
| `--log-dir` | Write the logs to another folder |

## Outputs

```text
experiments/execute/<your-run>/
├── inputs/
│   ├── specification.yaml
│   └── fixtures/
├── outputs/
│   └── trials/
│       └── <trial>/
│           ├── record.json
│           ├── evidence/
│           └── artifacts/
└── logs/
    ├── events.jsonl   # One progress event per line
    └── simulate.log
```

`logs/events.jsonl` records the progress of the run as it happens, one JSON event per line, so
another program can follow the run. The schema of each line is
`packages/core/schemas/run-event.schema.json`.

## Next step

[Run the graders](run-graders.md).
