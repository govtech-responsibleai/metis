# Grader guide

This guide gives what you need to write or review a grader. For the list of graders and the
prompt that each one adapts, see the
[grader catalogue](../../../packages/library/src/metis/library/graders/README.md).

## What a grader does

A criterion in `specification.yaml` names one grader class and gives its settings:

```yaml
grader_fqn: metis.library.graders.OutputCorrectnessGrader
grader_args:
  correctness_conditions:
    - The total matches the sum of the line items.
```

After a simulation, the engine gives the grader the recorded session for one trial. The
grader returns one result for each part of the session that it judged. A result is `scored`
with a score of `1` (pass) or `0` (fail), or it is `errored` with a reason. An errored result
has no score and does not count as a failure. The scope sets how many results there are (see
[Results and records](#results-and-records)).

A grader does not see the scenario, the persona, or the stop reason. It sees only the
recorded traces and the files that the run produced (`GradingInput`).

## The parts of a grader

Each grader is one module in `metis/library/graders/<sub-dimension>/`. It has three parts.
`OutputCorrectnessGrader` in `task_and_output_quality/_output_correctness.py` is a short
example of all three:

1. **An arguments model.** It validates `grader_args`. Every grader gets `threshold` from
   `GraderArgs`. A model-based grader extends `JudgeArgs`, which adds `model` and
   `max_input_tokens`. It also inherits the settings
   class for each scope that it supports, such as `TraceArgs` (see [Scopes](#scopes)).
   Unknown keys fail validation before the run starts.
2. **A `taxonomy` declaration.** It names the one measure that the grader assesses and the
   values that it supports (see [Taxonomy](#taxonomy)).
3. **`criteria()` and `grade()`.** `criteria()` returns the rubric text that the judge reads.
   `grade()` selects what to judge and calls the judge once for each selected piece.

Most model-based graders use this `grade()` without changes:

```python
async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
    scope = SCOPE_DEFINITIONS[self.scope]
    selected = scope.select(input, self.args)
    if isinstance(selected, Problem):
        return GradingOutput.errored(selected.detail)
    return GradingOutput(
        results=[
            await judge(self, llm, label, scope.render(thing), self.criteria())
            for label, thing in selected.items()
        ]
    )
```

So the work in a new grader is mostly the arguments and the rubric. The shared code does the
rest:

| Module | What it does for you |
|---|---|
| `metis.library.scope` | Selects the part of the session to judge and renders it for the judge. |
| `metis.library.judge` | Builds the prompt, calls the model, checks the input size, and turns the reply into a result. |
| `metis.library.judgment_form` | Gives the binary output rules and validates the reply. |
| `metis.library.aggregation` | Combines the results of a grader that checks several rules. |
| `metis.core.trace_processing` | Reads the traces: recorded turns, tool calls, errors, and files. |

## Scopes

In this guide, in the `turn` setting, in `turn:N` labels, and in the prompts sent to the judge,
"turn" means a **recorded turn**: one trace of the target's session, as defined in
[`GLOSSARY.md`](../../../GLOSSARY.md). It never means a simulated turn, which is one exchange
in the engine's simulation loop. The prompts keep the bare word because the transcript the
judge reads has `## Turn N` headings.

The scope decides what one result is about. A grader declares the scopes that it supports.
A criterion selects one with `grader_args.scope`. When `scope` is not set, the grader uses the
first scope that it declares.

| Scope | One result is about | Label | Settings |
|---|---|---|---|
| `TRACE` | One recorded turn | `"turn:3"` | `turn`: `each` or `last` |
| `SUBSESSION` | One recorded turn, with the recorded turns before it as context | `"turns:2-4"` | `turn`, and `window` (number of recorded turns) |
| `SESSION` | The whole session | `"session"` | None |
| `ARTIFACT` | The latest version of one file that the target produced | `"artifact:a.pdf"` | `artifact`: the file name |

At `ARTIFACT` scope, the judge reads the file itself. METIS does not extract text from it.

## Results and records

Three models carry a grader's output, from the grader to `results.json`:

| Model | Made by | Holds |
|---|---|---|
| `GraderResult` | The grader | `status` (`scored` or `errored`), `score`, `reason`, and `scope`, the label of what it judged |
| `RecordedResult` | The engine | The same result with an `outcome`: `passed` or `failed` from the criterion's `threshold`, or `errored` |
| `GraderRecord` | The engine | One grader run on one session: the session, scenario, task, trial, criterion, resolved `grader_args`, `aggregation`, and the list of `RecordedResult` |

A grader never decides pass or fail. It returns a score, and the engine applies the threshold.

### How many records

The engine runs each criterion's grader once on each session. So `results.json` has one
`GraderRecord` for each criterion and each session. For example, 3 criteria and 4 sessions
give 12 records.

### How many results in one record

The select function of the scope sets the count. It returns one entry for each thing to
judge, and `judge` makes one `GraderResult` for each entry. `turns()` makes one recorded turn for each
trace, so for a session of N traces:

| Scope | Setting | Results | Labels |
|---|---|---|---|
| `TRACE` | `turn: each` | N | `turn:1` … `turn:N` |
| `TRACE` | `turn: last` | 1 | `turn:N` |
| `SUBSESSION` | `turn: each` | N | `turns:1-1` … `turns:1-N` (with `window: 2`: `turns:1-1`, `turns:1-2`, `turns:2-3` …) |
| `SUBSESSION` | `turn: last` | 1 | `turns:1-N`, or the last `window` recorded turns |
| `SESSION` | None | 1 | `session` |
| `ARTIFACT` | `artifact: <name>` | 1 | `artifact:<name>`, the latest version of the file |

A grader that checks several rules still gives one result for each entry. It calls `judge`
once for each rule, and the aggregation combines the rule results into one result. So
`RequiredComponentCompletenessGrader` with 5 components at `turn: last` makes 5 judge calls
and gives 1 result.

There is always at least one result:

- **The session cannot be judged.** This happens when the session has no recorded turns, the named
  file does not exist, or the evidence that the measure needs is missing. The grader returns
  one errored result with no `scope` label.
- **One entry cannot be judged.** For example, the reply of one recorded turn cannot be read. That
  entry gives an errored result with its label. The other entries are still judged.
- **The grader raises an exception, or returns an empty list.** The engine records one errored
  result in its place.

So the count depends on the scope and the session length. A grader that judges each recorded turn gives 10 results on a session of 10 recorded
turns, and a session grader gives 1. A report must show the number of
results beside each rate.

## Three patterns for grade()

| Pattern | What `grade()` does | Example |
|---|---|---|
| One criterion | The code above. | `OutputCorrectnessGrader` |
| Several rules | Calls `judge` once for each rule, then combines the rule results with `AGGREGATION_DEFINITIONS[self.aggregation]`. | `TaskConstraintAdherenceGrader` |
| Output against sources | Calls `judge_against_sources`. It adds the earlier recorded turns and the files that the user gave the target. | `ClaimSupportByEvidenceGrader` |

The aggregation rules for several rules are these:

- `pass_if_all`: one failed rule gives `0`. Otherwise, one errored rule gives `errored`.
  Otherwise the result is `1`.
- `pass_if_any`: one passed rule gives `1`. Otherwise, one errored rule gives `errored`.
  Otherwise the result is `0`.

## Rules for results

- **Missing evidence is an error.** Before the judge call, check that the session has the
  evidence that the measure needs. For example, `ToolArgumentCorrectnessGrader` needs
  recorded tool calls. If the evidence is missing, return `GradingOutput.errored(reason)`, and
  say what is missing in the reason.
- **"Did not happen" is an error.** If the event that the criterion looks for did not happen,
  the judge replies `not_applicable`, and `judge` records an errored result. An example is an
  error recovery grader on a session that has no error.
- **Never score a `Problem`.** A trace processor function returns a `Problem` when METIS
  cannot read the evidence. Return it as `errored` with its detail. `judge` does this for you.
- **Never return an empty list.** A grader that cannot judge the session returns one errored
  result (see [How many results in one record](#how-many-results-in-one-record)).

## Reading traces

Do not read trace or observation fields in a grader. Use `metis.core.trace_processing`:

- `turns(input.traces)` gives one recorded turn for each trace, oldest first.
- `render_session` gives the text that the judge reads. It shows the user's message, system
  prompts, model output, sub-agent handoffs, tool calls and their results, errors, and the
  reply, in time order.
- `render_dialogue` shows only what the user and the agent said to each other.
- `find_artifacts` and `find_fixtures` give the records of the files that the target produced
  and the files that the user gave the target.

The render function of a scope gives `render_session` with tool results. A grader whose
measure needs other evidence calls its own render function in `grade()`, in place of
`scope.render`. For example, `ToneAppropriatenessGrader` judges only what the user reads, so
it uses `render_dialogue`. `OutputNaturalnessGrader` uses
`render_dialogue(turns, assistant_only=True)`, because it judges only the replies.

If a grader needs a view that does not exist, add it to `trace_processing.py` with tests in
`tests/unit/core/`. Do not build it in the grader.

A grader instance can grade several sessions at the same time. Do not change the input, and
keep only the arguments on the instance.

## Taxonomy

The `taxonomy` declaration describes the grader with one vocabulary. It has six fields:

| Field | Meaning | Most graders |
|---|---|---|
| `measure` | The property that the grader assesses. | One `Measure` value, such as `OUTPUT_CORRECTNESS` |
| `scopes` | The parts of a session that it can judge. | `TRACE` and `ARTIFACT`, `SESSION`, or `SESSION` and `SUBSESSION` |
| `grader_types` | How it judges. | `LLM` |
| `reference_types` | What it judges against. | `RUBRIC_BASED` or `EXPECTED_OUTPUT` |
| `judgment_forms` | The form of the result. | `BINARY` |
| `aggregations` | How it combines several rules. | `NONE_SINGLE_SCORE`, or `PASS_IF_ALL` |

Only three fields change what the code does: `scopes`, `judgment_forms`, and `aggregations`.
Each has a shared definition and a setting in `grader_args`. When a grader is built, it
rejects a setting that its taxonomy does not declare. The wizard shows a setting only on a
grader that declares more than one value. The other fields are descriptions only.

Declare only the values that the grader implements, and test each one. The taxonomy is a list
of supported values. It does not show that the grader is accurate.

## Adapted prompts

Some graders adapt their rubric from a metric in another evaluation package, such as DeepEval
or MLflow. These prompts are in wide use, so METIS copies the wording that fits the measure.
METIS removes the upstream output format, because every grader replies in the shared binary
form. It keeps the rule that a criterion that does not apply has no score. A grader with no
suitable upstream prompt uses a rubric written for METIS.

When you adapt a prompt:

1. Copy only from an MIT or Apache-2.0 source. For Phoenix, copy only from the JavaScript
   package `js/packages/phoenix-evals`, because its Python package has a different license.
2. In the module docstring, name the upstream file, the pinned commit, the license, and each
   change for METIS.
3. Add the project to
   [EXTERNAL_SOURCES.md](../../../packages/library/src/metis/library/EXTERNAL_SOURCES.md) if it
   is not there.
4. Link the upstream file in the grader catalogue.

To review an adaptation, compare `criteria()` with the linked upstream file.

## Checklist for a new grader

1. Write the arguments model. Extend `JudgeArgs` and the settings class for each scope.
2. Subclass `Grader[YourArgs]` and set `args_model = YourArgs`.
3. Declare the `taxonomy`.
4. Write `criteria()`, and use the `grade()` pattern that fits.
5. For a check that needs the specification, such as whether a named file exists, override
   `check_setup()`. The engine reports its errors before the run.
6. Export the grader from `metis.library.graders`, and add a row to the grader catalogue.
   Put example graders in `metis.library.graders.demo` only.
7. Run `make generate-grader-docs`. It writes the grader's page in `website/docs/library/` from
   the class docstring, the taxonomy, the arguments model, `criteria()`, and the grader
   catalogue. Run it again after any change to those. Do not edit the generated pages.
8. Add tests in `tests/unit/library/`. Test each declared scope, invalid settings, missing
   evidence, and a judge failure. Mock the model in the tests.
   `test_grader_docs.py` fails when a generated page or the docs data is stale.

The unit tests show that the grader runs. They do not show that it judges correctly. To
measure that, compare its results with human labels on representative sessions.

## Examples to copy

| Grader | Shows |
|---|---|
| `OutputCorrectnessGrader` | One criterion, at `TRACE` or `ARTIFACT` scope |
| `TaskConstraintAdherenceGrader` | Several rules combined by `pass_if_all` |
| `ClaimSupportByEvidenceGrader` | Output against sources |
| `FormatSchemaComplianceGrader` | A check in code before the judge call, and `check_setup()` |
| `RelevanceGrader` | `SESSION` by default, or `SUBSESSION` for one result for each recorded turn |
| `ToneAppropriatenessGrader` | Its own render function, `render_dialogue` |
| `ActionStatusTransparencyGrader` | An errored result before the judge call when the evidence is missing |
| `demo.DemoTraceBudgetGrader` | A deterministic grader with no judge call |
| `CriterionJudgeGrader` | The fallback judge, with `measure=None`. See the [Criterion Judge guide](criterionjudge.md). |

## Current limits

- Every grader gives a binary score. No other judgment form exists yet.
- The engine reads only the aggregation rule from the taxonomy. Insights and the report do
  not read it.
- Insights combines the results of one grader run with an equal-weight mean. How results
  combine across trials is not decided yet.
- A subset of a session other than a run of recorded turns, such as the recorded turns of one sub-agent, needs
  a new select function.
