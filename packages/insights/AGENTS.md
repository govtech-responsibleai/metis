# metis-insights

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

## Package Purpose

Report generation for evaluation outputs. `metis insights report --results-file <path>`
reads core `EvaluationResults` from `outputs/reports/results.json` and produces the
terminal passed/failed/skipped/errored summary plus `outputs/reports/report.json` and
`outputs/reports/report.html`.

## Dependency rule

Depends on `metis-core` only. Never import `metis.engine`, `metis.library`, or
`metis.wizard`; `tests/unit/insights/test_dependency_boundary.py` checks this.
The core `EvaluationResults`, `GraderRecord`, `RecordedResult`, and `TrialRecord`
models own the saved input contracts. Insights owns the private output `Report` model.
Preserve recorded Criterion IDs, grader settings, and Task and Trial identity. Keep grader
errors separate from target failures and skips.

## Layout

- `cli.py` — the Typer app (`metis insights …`)
- `report.py` — `format_terminal_summary`, `save_report`
- `_models.py` — `Report`, the `report.json` contract
- `_report.py` — `build_report`, `load_report_sources` (the behaviour/criterion rollup)
- `_aggregation.py` — summary counts and the mean of children
- `_report_page.py`, `_report_styles.py` — the HTML page. `RENDER_SCRIPT` holds pure
  functions that turn report data and a view state into HTML strings. `WIRING_SCRIPT` holds
  the view state and the click handlers. Page tests run the renderers in Node through
  `tests/fixtures/insights/report_page.py`.

## Run calculations

Summarize each grader record once. Use the equal-weight mean of scored results and
the recorded threshold. A criterion pools its runs. Every level above it takes the
unweighted mean of its evaluated children (`_aggregation.mean_of`). Round only for output.
Keep raw result evidence separate from run counts. Use `grader_name` and `grader_fqn` in
report fields. See the [report contract](../../docs/guide/report.md).

## Report contract

`_models.Report` defines and validates `report.json`. `metis.insights` re-exports it. Reports contain
`schema_version: 1`. The model defaults a missing version to `1` and rejects other
explicit versions. There is no published JSON Schema file for reports. `Report` stays in
insights while no other package reads `report.json`. Move it to core when a second package
needs it.

The report's content rules live in [docs/guide/report.md](../../docs/guide/report.md).
