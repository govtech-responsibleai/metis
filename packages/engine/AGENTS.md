# metis-engine

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

## Package Purpose

Evaluation runtime — simulation harness, trace extraction, and grader execution. Report generation lives in `metis-insights`.

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
4. Update `examples/http-agentic_eval_toyapp-1/specification.yaml` if affected
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
- To test the Langfuse fetch, call `fetch_session` with a fake client whose `get_many` answers
  by filter column (see `tests/unit/engine/test_extractor_fetch.py`), so a fetch that reuses the
  session-filtered rows as a trace's observations (issue #435) fails. Do not hit the live
  Langfuse API.
