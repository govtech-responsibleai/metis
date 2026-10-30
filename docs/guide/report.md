# Report Contract

This document defines the target and data contract for the METIS target evaluation
report. The
report is an investigation dashboard for a target owner. It presents evaluation
evidence. It does not make release decisions or set target priorities.

## File contract and current input support

The insights [Report model](../../packages/insights/src/metis/insights/_models.py) defines `report.json`.
The report writer validates data through this model. Saved reports contain `"schema_version": 1`.
The model defaults a missing version to `1` and rejects other explicit values.

The Insights CLI reads `metis.core.reporting.EvaluationResults` from
`outputs/reports/results.json`. Each `GraderRecord` in its `records` list is one grader run
on one session, with one or more `RecordedResult` entries. The command joins records to the
frozen `inputs/specification.yaml` and to the saved `outputs/trials/*/record.json` files.
Trial conversations come from the traces in `outputs/traces/` that `evaluate` saved.
It writes `report.json` and an offline `report.html` beside the results file. A results
file in the format from before the grader redesign has `turn_results` or `session_results`.
The CLI rejects that file and writes no report. Insights does not create graders.

## Reader and purpose

- The primary reader is the target owner.
- The report shows all measured target features and lets the target owner decide what to
  investigate or prioritize.
- The report can state direct facts from the evaluation data. It must not add urgency,
  investment, release, or target-priority judgements.
- The report must keep the detailed evidence needed by evaluators.

## Summary facts

The page opens with these facts:

1. The average pass rate, which is the headline result of the
   [hierarchy roll-up](#hierarchy-roll-up). Its tip explains how it is calculated and names
   the pass-rate target.
2. Behaviours below the target, as a count of the behaviours that have a rate.
3. Trials that reached their goal, from `trials.successful` of `trials.attempted`.
4. The number of test cases.

The header shows the target name and the report date. Generate all values from report data.
The page does not show a run start time or a run duration, because the run does not record
them.

## Pass-rate target

`report.json` records `passRateTarget`, which is 70. The page shows a rate in red when it is
below this target. A missing rate is never red. The target is a fixed value in
`metis-insights`. It does not change any `status` field or any grader verdict. A grader's
`threshold` decides if one run passes. The pass-rate target is only for display.

## Temporary pass contract

A grader returns one result for each scope item, such as one trace or the whole session.
Each result is already combined inside the grader by its declared aggregation. See the
[grader guide](library/graders.md). The report reads only the recorded results. It does
not inspect the grader. How the results of one record combine into one run score is not
decided yet. Until then, the report uses this contract:

1. Each `GraderRecord` is one grader run. Its combined score is the equal-weight mean of
   its scored results.
2. Compare the combined score with the recorded `grader_args.threshold`. A score at or above
   the threshold passes. A lower score fails.
3. A scored run needs a finite numeric threshold from 0 to 1. A missing or invalid threshold
   stops report generation, and the error names the run.
4. A run with no scored results is errored if any result errored. Otherwise, it is skipped.
5. Exclude skipped and errored runs from rates and mean scores. Record their counts with
   every rate and mean score.
6. Record the numeric rate, mean score, status, recorded threshold, judge model, and
   passed/failed/skipped/errored counts in `report.json`.

Partial skipped or errored results stay visible as raw evidence when a run has scored
results. They do not add extra run verdicts. Original result outcomes and scores stay
unchanged.

The page uses these result words: Passed, Failed, Skipped, and Errored. Errored means that a
grader run failed. This says something about the grader, not the target. A behaviour that
the specification does not measure shows "Not measured". An item with no graded run shows
"Not graded" or "—".

## Hierarchy roll-up

Each item has two numbers in `report.json`:

- **Pass rate:** the share of grader runs that passed. A run passes when its score is at or
  above the recorded threshold.
- **Mean score:** the average score from 0 to 1, before the threshold.

The page shows the pass rate on every item. It shows the mean score only in the detail
panel of a criterion.

The two numbers can differ. Runs that score just below the threshold give a low pass rate
and a high mean score.

The table shows how each item calculates both numbers, from the most detailed item to the
least detailed. A grader run is one `GraderRecord`.

| Item | How it is averaged |
| --- | --- |
| Grader run | Equal-weight mean of its scored results. The run passes or fails by the [temporary pass contract](#temporary-pass-contract). The test case panel shows one grader run for each criterion in each trial. |
| Grader runs across all trials of one test case | Mean of the grader runs of one criterion, over all trials in one test case. The results table shows this number in each cell. |
| Criterion | Mean of all its grader runs, over all test cases. |
| Behaviour | Mean of its evaluated criteria. |
| Feature | Mean of its evaluated behaviours. |
| Headline result | Mean of the evaluated features. |

Every mean is unweighted, so each item in it counts once. For a pass rate, a passed run
counts as 1 and a failed run as 0. The mean of a criterion's runs is therefore passed runs /
evaluated runs. A behaviour takes the mean of its criteria and not of their runs. A
criterion with many runs then has the same weight as a criterion with few runs.

`report.json` also has persona and scenario rows in `axes`. Each row is the mean of the
evaluated criteria, each calculated over the runs for that persona or scenario. These rows
have a pass rate only. The HTML page does not show them.

The terminal summary has one row per criterion and grader, which uses the criterion rule.
Its last row is the mean of the criterion rows.

These rules apply to every item:

- An evaluated run passed or failed. Skipped and errored runs are left out of rates and mean
  scores.
- A child counts only when it has at least one scored run. A node with no usable evidence
  is Not evaluated.
- A grader setup or mapping problem is Data error.
- Counts beside a rate are the totals of the runs below it. They show coverage. They do not
  weight the mean. Calculate from unrounded values.

The normalized profile gives each criterion a name and an ID. Report JSON uses the criterion
ID as the criterion key. Each criterion also has `name`, and `names.P` and `names.S` map
persona and scenario IDs to their names. The page shows these names and falls back to the
ID when a name is missing. A criterion names one grader. Criteria, table
columns, and unmapped entries use `grader_fqn` for the full grader path and `grader_name`
for its display label. The display label never identifies a criterion or a recorded
result. Scores retain Task, Trial, Session, Criterion, Grader FQN, and arguments.
IDs join Features, Behaviours, Criteria, Personas, Scenarios, Tasks, and
grader records. The insights [Report model](../../packages/insights/src/metis/insights/_models.py)
defines these fields.

A record joins to a criterion through its task and criterion IDs. The recorded scenario must
match the task scenario, and the task must select the criterion's behaviour. When trial
records are available, a record joins to a trial through its task ID, trial index, and
session ID. A different session cannot inherit that trial's persona or outcome. The report
rejects two grader records for the same task, trial index, session, and criterion.

The terminal summary includes all stored grader runs, with one row per criterion and grader.
It has no specification, so its last row is the unweighted mean of the criterion rows. The
report's hierarchy, axes, and headline use runs that match the specification. Unmatched runs
stay in `unmapped` with a reason and their original grader records. Distinct reasons stay in
separate groups. The top-level `results` count includes every raw result, including
unmatched results.

These rules are report inputs. The report must not replace an aggregator-supplied rate
or aggregation method.

## Repeated-trial uncertainty

Each `resultTable.rows[].results[criterion_id]` cell has `confidence_interval`.
Insights calculates a 95% Wilson interval from the passed and failed grader runs for that
Task and Criterion. Each run counts once, including runs with multiple raw scores.
Skipped, errored, and missing runs do not enter the interval. Their existing counts and
coverage information stay separate. A run with scored results keeps its verdict under
the [temporary pass contract](#temporary-pass-contract), even when some raw results errored.

The interval object has `method: "wilson"`, `confidence_level: 0.95`, and `lower` and `upper`
limits. Limits are unrounded proportions from 0 to 1. The cell's `evaluated` field is the
sample count. A cell with no passed or failed runs has `confidence_interval: null`.
One evaluated run is sufficient to calculate an interval. Small samples give wide intervals,
including when all observed runs pass or all fail.

The interval estimates the pass probability for repetitions of the same test case under
the same settings, among runs with a valid grade. It assumes independent trials with a
common pass probability. It does not measure coverage of other scenarios or separate
target, simulated-user, and judge variation. The 95% confidence level describes the
long-run coverage of this calculation across repeated experiments.

Intervals apply only to pooled Task and Criterion cells. Individual trials, criteria
pooled across tasks, features, axes, and headline rates have no interval. The HTML results
table shows each cell's interval in brackets under its rate. The test case panel shows the
interval of each criterion as a range bar against the pass-rate target. The terminal output
does not display it. The specification and engine output formats are unchanged.

## Failure evidence

- Each trial shows its recorded ending: reached its goal, stopped, error, or timed out. A
  trial that ended early shows the recorded message, the recorded failure source, and the
  attempt number when the trial was retried.
- The report shows the recorded failure source. A target-response error is from the
  target. A user-agent LLM failure is from the user agent. A simulation crash is from
  the evaluation runner.
- For old records that do not contain a failure source, the report can use the matching
  simulation log only when the log explicitly names the source.
- The report does not infer a failure source from message text. It does not assign a
  cause. It keeps the recorded message text.
- The report does not adjust scores or exclude unsuccessful trials.
- For each criterion in a trial, show what its grader returned for that trial. Show the
  recorded reason when the result has one. Otherwise, show the recorded result as it is.
  When a run has more than one result, show each one.
- Core results do not store a trace ID or a conversation position, and the report does not
  infer either value. The page does not link a result to a turn.
- Show results that match no Task and Criterion in a separate `Results without a matching
  criterion` section. Group them by criterion ID, grader FQN, and reason. Each result keeps
  an expandable `Recorded grader settings` section. These results are excluded from the
  target pass rate.

## Information architecture

The page is one page, with no tabs. Explanations are in tips. Run facts are in a closed
`Run details` section at the end.

**Specification results**

- Show every feature, behaviour, and criterion in the order of the specification. The page
  has no sort controls and no search.
- Show the hierarchy as a list by default, with a switch to a tree. The tree has the target
  as its root and has no separate grader node. Each row or box shows only the name and the
  score. The reader can open and close each feature and behaviour.
- Fit the section to 70% of the window height. The list, the tree, and the detail panel
  each scroll inside it.
- A click on a criterion opens it in the detail panel. The panel shows the parent behaviour,
  the criterion description, grader, judge model, pass mark, mean score, counts, and one row
  for each test case. A click on a test case opens it in the test case panel.

**Results by test case**

- Use one row per Task. Group criterion columns by feature. The header rows and the test
  case column stay in place when the reader scrolls.
- In each cell, pool the grader runs of all trials in that Task for that criterion. Show
  the pass rate on a colour scale from soft rose at 0% to soft teal at 100%, and the 95%
  interval in brackets under it. Exclude skipped and errored runs from the rate.
- Show the skipped and errored counts of each row under its test case name.

**Test case panel**

- A click on a test case opens a panel from the right. It shows only that test case.
- Show the number of trials that ran and the number that reached their goal.
- For each criterion, show the pass rate, the 95% interval as a range bar against the
  pass-rate target, the interval limits, and the passed and graded counts.
- Show one row for each trial, with its ending, its first user message, and its result for
  each criterion. The first trial is selected when the panel opens.
- For the selected trial, show the conversation with user messages on the right and target
  replies on the left. Beside it, show what each grader returned, in one tab for each result:
  Failed, Passed, Errored, and Skipped. Trial data carries the engine's count of simulated
  turns as `simulated_turns_completed`.
- The page counts only recorded turns, as defined in the [glossary](../../GLOSSARY.md). Each
  conversation row is one recorded turn, numbered as the graders number it (`Turn N` is
  `turn:N`), and the trial's ending gives the number of rows. The page does not show
  `simulated_turns_completed`, which counts simulated turns.

## Implementation boundary

The report file contract, report generation, and its content rules belong in
`metis-insights`. A generated report file is not a source of truth.

The report must accept future aggregator-owned fields without changing this interface
contract. The aggregator can take full ownership of rates, thresholds, counts, statuses,
and aggregation methods in a later change.
