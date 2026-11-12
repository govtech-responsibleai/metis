# metis-engine

Evaluation engine for METIS — simulation harness, trace extraction, and grader execution. Report generation lives in `metis-insights`.

## What it does

1. **Simulate** — drives the target system through its selected runner with LLM-powered user personas
2. **Extract** — fetches every Langfuse trace of each session
3. **Evaluate** — runs each criterion's grader once per session
4. **Results** — writes grader results to `outputs/reports/results.json` (holding one GraderRecord per grader per session; `metis insights report` reads it)

## Setup

```bash
# From the monorepo root
make install                    # installs workspace dependencies

# Configure environment
cp .env.example .env
# Fill in: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, OPENAI_API_KEY,
#          LANGFUSE_BASE_URL, TOYAPP_API_URL
```

The [model guide](../../docs/guide/models.md) lists the model variables of each role and the
Specification fields that record the models.

## Running

These commands use the `simple` example, which is small enough for a quick first run (see its
[README](examples/README.md)).

```bash
# Run end-to-end (Simulation TUI, then evaluation progress bar)
metis engine run --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/

# Or run the phases separately, in this order. simulate prints the evaluate command.
# The --experiment-dir value is the output directory that simulate created.
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/
metis engine evaluate --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/

# Resume an interrupted simulation. simulate prints this exact command;
# --experiment-dir is the output directory to continue.
metis engine simulate --resume --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/
metis engine run --resume --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/

# Resume an interrupted evaluation. Trials that already have a file in outputs/evaluation/ are skipped.
metis engine evaluate --resume --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/

# With the browser runner selected and its credentials set:
HEADED=true metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/

# Verbosity controls log detail, not progress displays.
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ -v    # INFO
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ -vv   # DEBUG
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ --quiet  # ERROR only

# Disable the Simulation TUI (force linear simulation output)
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ --no-tui

# Structured log files (JSON lines)
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ --log-format json

# Override log directory (default: co-located with results)
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ --log-dir /tmp/my-logs

# Concurrent simulation (2 parallel browser contexts)
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/ --concurrency 2

# Custom Langfuse timeout for evaluation (default: 90s)
metis engine evaluate --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/ --langfuse-timeout 120
```

| Command | Reads | Writes |
|---------|-------|--------|
| `simulate` | `specification.yaml` and `fixtures/` from `--input-dir` | `experiments/execute/<id>-<timestamp>/outputs/trials/` |
| `evaluate` | `outputs/trials/` from the `--experiment-dir` output directory,  the Langfuse traces it points to, and `inputs/specification.yaml` from that output | `outputs/evaluation/`, `outputs/traces/` and `outputs/reports/` in that same output directory |

> **Important:** `evaluate` must only be run after `simulate`. It scores an existing simulation output rather than producing one, so if the directory holds no `inputs/` snapshot it exits 1 and tells you to run `simulate` first.

The two commands take different paths. `simulate` takes the source experiment as `--input-dir`. `evaluate` takes one simulation output directory as `--experiment-dir`, so the scored output never depends on timestamps. `simulate` prints the exact `evaluate` command for the directory it created.

`experiments/execute/toyapp-http-simple-20260820-143000/` in the examples above is only a sample name. `simulate` makes the real name from the experiment `id` and the start time of the run. Use the path that `simulate` printed.

Evaluation has no TUI option. It uses a normal progress bar in a terminal and linear per-record progress in a non-interactive environment.

Resume continues the output directory named by `--experiment-dir`. It reads the experiment and fixtures from that directory's frozen `inputs/` snapshot, retries only missing, invalid, or `system_error` records, and appends to `logs/simulate.log`. `simulate` and `run` print the exact resume command. Passing `--resume` with `--input-dir` is an error; the message lists the outputs that exist for the experiment `id`. A resumed simulation that re-runs at least one trial deletes `outputs/evaluation/`, `outputs/traces/` and `results.json`, because the old grades no longer match. With nothing to redo, it keeps them.

`evaluate --resume --experiment-dir <dir>` skips every trial that already has a file in `outputs/evaluation/`, grades the rest, and prints `resuming: K of N trials already evaluated`. A trial counts as evaluated once it has that file, whether it was graded, had errored criteria, or failed before grading. Resume does not retry failed trials or errored criteria; to grade every trial again, run a fresh `evaluate`. A fresh `evaluate` deletes `outputs/evaluation/`, `outputs/traces/` and `results.json` once its setup checks pass, then grades every trial. If `results.json` exists, `--resume` prints `nothing to resume` and changes nothing. It appends to `logs/evaluate.log`. Ctrl-C keeps the files of the trials that finished, writes no `results.json`, and prints the resume command; trials in flight are lost, at most `--concurrency` of them. `run --resume` resumes the simulation, then the grading.

### Concurrency

The `--concurrency N` flag runs N browser contexts in parallel on a single browser process. Each worker gets its own isolated login session and page — no shared state, no cookie leakage between workers.

Runs are distributed round-robin across workers for balanced load. The default (`1`) preserves sequential behaviour; increase based on target system capacity.

## Experiments

An experiment is a directory containing `specification.yaml` and a `fixtures/` folder:

```
my-experiment/
├── specification.yaml  # Target, Criteria, Personas, Scenarios, and Tasks
└── fixtures/            # Files uploaded during simulation
    └── data.csv
```

See [`examples/http-agentic_eval_toyapp-1/`](examples/http-agentic_eval_toyapp-1/) for a working reference.

Each execution produces output in `experiments/execute/<id>-<timestamp>/`, under the project folder. Reports appear after `evaluate` or `run`. The project folder is the working directory or the nearest folder above it that has a `pyproject.toml`. `simulate` and `run` take `--project-dir <folder>` for an existing folder to set it from any working directory.

```text
experiments/execute/toyapp-http-simple-20260730-143022/
├── inputs/
│   ├── specification.yaml
│   └── fixtures/
├── outputs/
│   ├── trials/
│   │   └── TC-001-cooperative-delegator-1/
│   │       ├── record.json
│   │       ├── simulate.log       # Link to the trial log
│   │       ├── evidence/
│   │       │   ├── llm_calls.jsonl  # One row per user-agent and runner-agent LLM request
│   │       │   └── log.jsonl        # One entry per request and response
│   │       └── artifacts/
│   │           ├── run-manifest.json
│   │           └── ...
│   ├── evaluation/
│   │   └── TC-001-cooperative-delegator-1.json  # One file per trial evaluated; private to the engine
│   ├── traces/                    # Raw Langfuse rows saved by evaluate
│   └── reports/
│       ├── results.json           # Engine evaluation, written last
│       ├── report.json            # Insights
│       └── report.html            # Insights
└── logs/
    ├── events.jsonl               # One PhaseEvent per line, for simulate and evaluate
    ├── simulate.log
    ├── simulate-TC-001_cooperative-delegator-01.log
    ├── llm_calls.jsonl            # LLM requests made once per experiment
    └── evaluate.log
```

`logs/events.jsonl` is the experiment's progress for other programs. Each line is one
`PhaseEvent` from `metis.core.phase_events`, validated by
`packages/core/schemas/phase-event.schema.json`. Every line has `seq`, `at`, `phase`
(`simulating` or `evaluating`), `trial` and `status`. Each phase starts and ends with a line
that has no `trial`. `seq` numbers the lines from 1 and continues when a resume or a later
`evaluate` appends. The file always stays in the
experiment folder, also when `--log-dir` moves the other logs.

## Programmatic usage

```python
from metis.engine import build_grader, fetch_session, grade_session
from metis.engine.extractor import get_langfuse_client
```

`fetch_session(session_id, langfuse, experiment_root=...)` is a coroutine: `await` it
from async code, or run it with `asyncio.run`.

`build_grader(criterion, default_judge_model=..., env=...)` returns a validated
`Grader` instance. Keep one instance per Criterion ID. Pass the selected Criteria
and the instance map to `grade_session(criteria, graders, grading_input, llm, facts)`.
Use Criteria from the specification snapshot. Trial references select their IDs
and order. The same instance can grade each required session.

Build a report from saved results with `metis.insights.save_report` or `metis insights report`.

## Schema management

`metis-core` publishes the `specification.yaml` schema. After you change the shared models, run:

```bash
make -C packages/core generate-schema
```

See [`packages/core/schemas/README.md`](../core/schemas/README.md) for versioning rules.
