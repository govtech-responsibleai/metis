# metis-library

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

## Package Purpose

Shared catalog of metrics, skills, and reusable components consumed by both the execution path (metis-engine) and the configuration path (metis-wizard). The wizard references items by FQN and passes them to the engine. Depends only on metis-core.

## Package-Specific Notes

- Graders do not read traces. They call `metis.core.trace_processing` for turns, tool
  calls, and the text views they send to a judge. Do not read observation fields such as
  `input`, `output`, `level`, or `status_message` in a grader. Do not build a view of a
  session in a grader. If a grader needs a new view, add it to the trace processor, with
  tests in `tests/unit/core/`. See the "Reading traces" section of
  `docs/guide/library/graders.md`.
- A model-based grader subclasses `Grader[Args]`. Its `grade()` selects what to judge with
  `SCOPE_DEFINITIONS[self.scope].select(...)`, renders each selected piece with the scope's
  `render`, and calls `metis.library.judge.judge` for each one. The definitions live in `metis.library.scope`, `metis.library.judgment_form`, and
  `metis.library.aggregation`. Add a definition there when a grader needs a new value.
