---
title: Run your evaluations
---

An evaluation has two steps. **Simulate** drives your application with simulated users and
records each conversation. **Evaluate** reads those conversations from Langfuse and runs the
graders. Run them one at a time, or together with `metis engine run`.

Before you start, finish the [pre-requisites](prerequisites.md) and
[build your specification](wizard.md).

## 1. Prepare the input folder

Put everything the run needs in one folder:

```text
my-evaluation/
├── specification.yaml
├── target-binding.yaml     # The target connection. The file name is free.
└── fixtures/               # Files that your test cases upload, if any
```

Name the target connection in `specification.yaml` with `target_binding:`. See
[Target connection](target-connection.md) and [Choose the runner](specification-file.md#choose-the-runner).
The wizard writes this folder for you.

## 2. Simulate

```bash
metis engine simulate --input-dir my-evaluation
```

METIS opens a progress screen in a terminal. When it finishes, it creates an output folder
under `experiments/execute/`, and prints the exact `evaluate` command for that folder and the
exact command to resume. The folder name comes from the experiment `id` and the start time, so
use the path that `simulate` prints.

Simulation does not need Langfuse. See [Run the test suite](run-test-suite.md) for the options.

## 3. Evaluate

```bash
metis engine evaluate --experiment-dir experiments/execute/<your-run>
```

This reads the traces from Langfuse, runs the graders and writes `results.json`. See
[Run the graders](run-graders.md).

## Or do both in one command

```bash
metis engine run --input-dir my-evaluation
```

`run` accepts the options of both steps, and its `--no-tui` controls only the simulation screen.

## What you get

```text
experiments/execute/<your-run>/
├── inputs/                 # A frozen copy of your specification and fixtures
├── outputs/
│   ├── trials/             # One folder per trial, with its record and artifacts
│   └── reports/
│       └── results.json    # Written by evaluate
└── logs/                   # simulate.log, evaluate.log, and more
```

A run that only simulated stops after `outputs/trials/` and `logs/`.

## Next step

[Read your report](report.md).
