# metis-core

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

## Package Purpose

Core data models and abstractions for the METIS suite. Zero workspace dependencies — only Pydantic v2, python-dotenv, and stdlib.

## Shared schemas

Core owns all new shared file contracts. Published
`*.schema.json` files belong in `packages/core/schemas/` and must be generated from
core models. Register new schemas in `scripts/generate_schema.py`. Run
`make -C packages/core generate-schema` and `make -C packages/core check-schema`.
Private runtime models and API models stay in their owning packages. See the
[schema guide](schemas/README.md).

## Package-Specific Notes

- Dependencies: Pydantic v2, structlog, Rich, python-dotenv (plus stdlib). Zero workspace dependencies.
- Public logging API: `from metis.core.logging import get_logger, configure_logging`
- Public console API: `from metis.core.console import console`

- `metis.core.profile` owns Target context, Features, Behaviours, and Criteria.
- `metis.core.experiment` owns Personas, Scenarios, Tasks, and execution settings.
- `metis.core.specification` combines a Profile and an Experiment. Its document
  adapter keeps YAML and API JSON flat.
  Keep draft construction separate from complete execution validation.
  `SpecificationDocument` is the source of `schemas/specification.schema.json`, the one
  published schema for `specification.yaml`. After changing it or a model it contains, run
  `make -C packages/core generate-schema` and commit the result.
- `target_binding.py`: `TargetBinding`, the YAML file a user writes by hand to bind an app
  to the generic HTTP or browser runner (`transport`). Source of `schemas/target-binding.schema.json`. Core checks
  its shape only; the engine loads it and expands `${NAME}` references. Secrets appear
  only as environment-variable names; validate it with `TargetBinding.model_validate` directly
  and never log `ValidationError.errors()` unredacted, or a pasted secret can leak. Call
  patterns reject OpenAPI `{name}` parameters. Not to be confused with `metis.core.profile.TargetProfile`,
  which holds the Target and its Features.
- `traces.py`: `Observation`, `Trace` and `GradingInput`, the read-only input of every grader
  run. Frozen, tuple collections. `Trace.root` is METIS's port of Langfuse's
  `isRootObservation = true` filter.
- `trace_processing.py`: the shared trace processor. Views (`Turn`, `ToolCall`), readers (the
  only code that reads `input`/`output`/`metadata`), `Problem` (data METIS could not read, never
  a target failure) and `TargetError` (evidence about the target). Graders and `metis-insights`
  read traces through it; it names no application.
- `grading.py`: `GraderResult`/`GradingOutput` (what a grader returns: a score, never a
  pass/fail) and `RecordedResult` (the outcome after the orchestrator applies the threshold).
- `reporting.py`: `EvaluationResults` (`outputs/reports/results.json`), one `GraderRecord`
  per grader per session. It is version-guarded like `TrialRecord` and has no published
  schema file.
- `model_settings.py`: the model and gateway of each LLM role (`ModelRole`, `ROLES`,
  `resolve_role`, `missing_settings`, `check_roles`) and the one `.env` search (`load_env`).
  Every command uses it. Keys and URLs come only from the environment; `RoleSettings` hides
  them from `repr`, and an error names variables, never values. See `docs/guide/models.md`.
- `trials.py`: `TrialRecord` (`outputs/trials/<trial>/record.json`) and the models it nests
  (`TrialConfig`, `TrialOutcome`, `TrialFailure`, `GraderRef`). The engine writes and resumes
  from it; the report reads it. Version-guarded by `_TRIAL_RECORD_VERSION`, no published
  schema file.
