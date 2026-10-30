---
title: How graders work
description: How the Wizard uses the Grader library, the settings a grader takes, and how a grader turns a session into scores.
---

import FlowSteps, {FlowStep} from '@site/src/components/FlowSteps';

The guided Interview is built on the Grader library. When the Interview writes a criterion, the Wizard uses the library as its reference to
assign a grader that measures that criterion, and then fills in that grader's settings. When no
grader in the library fits the criterion, or the matching fails, the Wizard falls back to the
[Criterion Judge](criterion-judge.mdx), which grades the session against the criterion
description.

## Grader settings

A criterion names its grader in `grader_fqn` and gives the grader's settings in `grader_args`:

```yaml
grader_fqn: metis.library.graders.OutputCorrectnessGrader
grader_args:
  correctness_conditions:
    - The refund amount is the order total minus the 10% restocking fee.
```

### Settings on every grader

| Setting | Default | Description |
| --- | --- | --- |
| `threshold` | `0.5` | A score passes when it is at least this value. |
| `model` | See below | The judge model for this criterion. |
| `max_input_tokens` | `128000` | The largest request that one judge call can send. A larger request gives an errored result. |

When you do not set `model`, the engine uses the experiment's `defaults.judge_model`, then the
`JUDGE_MODEL` environment variable, then its package default.

### Additional settings

Each grader page lists its own settings. These also shape how a grader judges:

| Setting | Description |
| --- | --- |
| `scope` | The part of the session that one result is about: one turn (`trace`), one turn with the turns before it (`subsession`), the whole session (`session`), or one file that the target produced (`artifact`). `turn`, `window`, and `artifact` refine the scope. When you do not set `scope`, the grader uses the first scope in its tag. |
| `judgment_form` | The form of each score, for example `binary`, a score of `0` or `1`. |
| `aggregation` | How a grader that checks several rules combines them. With `pass_if_all`, the score is `1` only when every rule passes. |
| Reference type | What the grader judges against: a fixed rubric, a reference that you supply, or rules that you list. It is not a setting itself. You give the reference through the grader's own settings, such as `ground_truth` or `constraints`. |

An unknown setting, or a value that the grader does not support, stops the run before it starts.

## How graders are used

<FlowSteps>
  <FlowStep title="Check">
    The grader checks that the session can be graded. If it cannot, the result is errored.
  </FlowStep>
  <FlowStep title="Grade">
    The grader judges the session and gives a score. The engine compares the score with
    <code>threshold</code> to decide pass or fail.
  </FlowStep>
</FlowSteps>

A result is also errored when the judge decides that the criterion does not apply, or when the
judge call fails. Errored results are not failures, and the report leaves them out of the pass
rate.
