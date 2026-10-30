# metis-insights

`metis insights report` turns the grader results of one evaluation into the target
evaluation report. It is the step after `metis engine evaluate` (or `run`), which scores
the traces and writes `outputs/reports/results.json` but builds no report.

## Usage

```bash
metis insights report --results-file experiments/execute/toyapp-http-simple-20260730-143022/outputs/reports/results.json
```

`evaluate` and `run` print this exact command, with the path already filled in, at the
end of their summary. The standalone `metis-insights report --results-file <path>`
behaves the same.

| Flag | Meaning |
|---|---|
| `--results-file PATH` | The `results.json` that evaluation wrote. A relative path resolves against the current directory. |

## What it reads and writes

The command finds the execution root from the `outputs/reports/` path. It reads
the input snapshot and trial records, then writes reports beside the results:

```text
experiments/execute/toyapp-http-simple-20260730-143022/
├── inputs/specification.yaml
└── outputs/
    ├── trials/*/record.json
    └── reports/
        ├── results.json
        ├── report.json
        └── report.html
```

Keep `results.json` inside its experiment's `outputs/reports/` directory. Run again after a new
evaluation and the report files are overwritten.

It also prints a terminal passed/failed/skipped/errored table per Criterion and grader, with the pass rate and mean score of its runs. Each grader run counts once. Its verdict uses the mean of scored results and the recorded threshold. The last row is the unweighted mean of the criterion rows.

## Outcomes

- **Report written.** Exit code 0, and the paths of both files are printed.
- **No specification.** When `inputs/specification.yaml` is missing or unreadable, the
  summary still prints, the command says which path it looked for, and it exits 0. A run
  without a target specification opts out of the report.
- **Invalid threshold.** A scored run with a missing or invalid recorded threshold exits 1 and writes no report. The error names the run.
- **Invalid results location.** A results file outside `outputs/reports/` exits 1.
  Keep the execution folder together when you move it.
- **Unreadable results.** A missing file, malformed JSON, or a `results.json` written by
  a different version of metis-engine (`Unsupported schema_version …`) exits 1 and
  writes nothing. Re-run `metis engine evaluate` to produce a current file.

The report's content — scoring, statuses, and failure evidence — is defined in the
[report contract](report.md), and its JSON shape in the
insights [Report model](../../packages/insights/src/metis/insights/_models.py).
