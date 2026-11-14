# metis-engine

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

## Package Purpose

Evaluation runtime — simulation harness, trace extraction, and grader execution. Report generation lives in `metis-insights`.

## Library functions

`metis.engine.runs` runs an experiment from Python, with no CLI. `metis engine simulate`,
`evaluate`, and `run` call these functions, and so does the API.

| Function | Does |
|---|---|
| `prepare_experiment(input_dir, *, project_dir, console)` | Checks the inputs, creates the experiment folder, copies the inputs in, and returns the folder. It calls no model. |
| `simulate(experiment_dir, *, concurrency, stop, console)` | Runs every trial in a folder that `prepare_experiment` made. |
| `resume_simulation(experiment_dir, *, concurrency, stop, console)` | Runs again only the trials that did not end. |
| `evaluate(experiment_dir, *, trace_wait, concurrency, stop, console)` | Deletes the earlier evaluation outputs and grades every trial. |
| `resume_evaluation(experiment_dir, *, trace_wait, concurrency, stop, console)` | Grades only the trials that have no evaluation file. |

The functions never exit and never set a signal handler. Each raises an error from
`metis.engine.runs.errors`: a `RunError` (exit code 1 in the CLI) or `RunStopped` (exit code
130). An unexpected error is raised as itself. `stop` is a `threading.Event`. When it is set,
a simulation ends each trial at its next turn, and an evaluation cancels its sessions within a
fraction of a second. The functions write their text only to `console`, which is a Rich
`Console`.

The caller sets up the process before it calls a function. It loads `.env`, calls
`metis.engine.tracing.tracing_key()`, and sets up process logging. The log router of a
simulation sits after the caller's log level filter, so the caller's log level also decides
what reaches the per-trial log files.

A process can safely run only one function at a time. Logging, the Langfuse clients in
`tracing.py`, and `os.environ["LANGFUSE_HOST"]` in `extractor/langfuse.py` are shared by the
whole process.

## Runner Contract

`docs/runner-contract.md` is normative for every `Runner` implementation. When changing a runner, `Observation`, or the orchestrator's handling of either, read it first and keep it in sync.

## Schema Sync

`metis-core` publishes the one `specification.yaml` schema, from `SpecificationDocument` in
`packages/core/src/metis/core/specification.py`. The engine has no schema files of its own. After
you change a shared model, run:

```bash
make -C packages/core generate-schema
```

Commit the updated schema file alongside the model change.

## Schema Versioning

When modifying `Specification` or `TrialRecord`, check whether the change is **breaking** — i.e., whether data valid under the current version would fail `model_validate()` under the new model.

**A bump is required for:** new required fields, type changes, field renames, breaking changes in nested models.

**No bump needed for:** new optional fields with defaults, removing fields (`extra="ignore"` silently drops them).

A breaking change to a nested model bumps the version of the root model that contains it:
- Shared Profile nodes, `Scenario`, `Task`, and `Criterion` → bump `Specification`
- `TrialConfig`, `TrialOutcome`, `TrialFailure`, `Artifact` → bump `TrialRecord`

### Bump Checklist

1. Increment `_SPECIFICATION_VERSION` in `metis.core.specification` or `_TRIAL_RECORD_VERSION` in `metis.core.trials`
2. Update the `Literal[N]` annotation on the model field to match
3. Run `make -C packages/core generate-schema` if `Specification` changed
4. Update `packages/engine/examples/http-agentic_eval_toyapp-1/specification.yaml` if affected
5. Note the schema version change in the commit message

See `packages/core/schemas/README.md` for the version policy.

## Two Langfuse projects

`LANGFUSE_*` names the Langfuse of the system under test. The extractor reads target traces
from it. The engine traces its own model calls to the METIS-internal Langfuse
(`METIS_INTERNAL_LANGFUSE_*`, see `src/metis/engine/tracing.py`). Every engine model client is
the `langfuse.openai` drop-in. A drop-in call that names no Langfuse key goes to whichever
client is registered, and in `evaluate` that is the target's. So every engine model call must
name `tracing_key()`:

- A simulation call goes through `parse_completion` or `create_completion`, which pass the key.
- Code that calls a client it does not own, such as a library grader, runs inside
  `tracing.traced`, which sets the key for every call nested inside.

`tests/unit/engine/test_internal_tracing.py` checks both paths with a target client registered.

## Pyright Configuration

The workspace disables `reportIncompatibleMethodOverride`. It was added for DeepEval's
`BaseMetric.__name__`; the redesign (#428) removed that cause and no override errors remain,
so re-enabling it is a safe follow-up.

## Test Style

- Unit tests do not touch the network. Build `Trace` / `GradingInput` objects directly for
  grader and orchestrator tests.
- To test the Langfuse fetch, await `fetch_session` with a fake client whose async
  `async_api.observations_v_2.get_many` answers
  by filter column (see `tests/unit/engine/test_extractor_fetch.py`), so a fetch that reuses the
  session-filtered rows as a trace's observations (issue #435) fails. Do not hit the live
  Langfuse API.
- `fetch_session` waits until Langfuse has stored nothing new for the quiet window. Pass it the
  `clock`, `sleep` and `utc_now` of a `FakeClock` (in the same file), so a test never waits in
  real time.
