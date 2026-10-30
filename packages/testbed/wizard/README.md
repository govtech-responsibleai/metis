# METIS testbed

The testbed checks how well Wizard turns product information into a Specification.
It compares each generated Specification with a human-reviewed reference.

## Run and compare versions

From the repository root, configure `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and an
`INTERVIEW_MODEL` that your API key can access. Set `INTERVIEW_CONTEXT_TOKENS` to
the model's supported limit when using large inputs.

```bash
# Run all four cases and save results under a version name.
uv run metis-testbed wizard --target-version version-a

# Run again after changing the Wizard version.
uv run metis-testbed wizard --target-version version-b

# Compare the latest saved run for each version. No model calls are needed.
uv run metis-testbed compare version-a version-b
```

Without `--target-version`, the command uses the current Wizard Git tag or branch
name. Results are saved under `packages/testbed/results/`, grouped by version and
run time. Open `report.md` for the run summary and linked case reports.

## Test cases

The suite contains four cases:

| Case | Product being described |
|---|---|
| [Enterprise AI Assistant](cases/enterprise-ai-assistant/README.md) | An assistant for enterprise information and workflows |
| [Travel Planner](cases/travel-planner-langgraph/README.md) | An assistant for planning trips |
| [Billing Support](cases/billing-support/README.md) | An assistant for billing requests and account actions |
| [Incident Triage](cases/incident-triage/README.md) | An assistant for assessing and routing incidents |

Each case supplies `inputs/prompt.md` and supporting documents. Its
`outputs/specification.yaml` is the reference.

## Testing and interpreting results

The testbed starts an Interview with each case's inputs, then asks Wizard to
finish. It accepts an enabled final Scenario review once. The reference is used
only for scoring; it is never sent to Wizard.

Completion and similarity are separate results. `scored` means the Interview
finished and scores were produced. `incomplete` means Wizard still needs a
response. Failures include the error and available diagnostic details. The command
exits with status `1` if any case fails or remains incomplete.

### Metrics

The scorer uses an embedding model to measure text similarity and match generated
items to reference items. A cache made with a different model is embedded again.
Matching is one-to-one and does not depend on item IDs or order.

Only the testbed uses an embedding model. Set these variables in `.env` to change it:

| Setting | Variable | When not set |
|---|---|---|
| Model | `EMBEDDING_MODEL` | `text-embedding-3-large` |
| API key | `EMBEDDING_API_KEY` | `OPENAI_API_KEY` |
| Base URL | `EMBEDDING_BASE_URL` | `OPENAI_BASE_URL` |

Each metric compares this information:

| Metric | Compared information |
|---|---|
| Feature | Name and description |
| Expected Behaviour | Name, description, parent Feature, and measurement selection |
| Criterion | Name and complete description within matched Behaviours |
| Grader | Exact Grader FQN and arguments for matched Criteria |
| Task | Scenario, Persona, Behaviour references, fixtures, and execution settings |

Each level score is the sum of matched similarities divided by the larger item
count. Missing or extra items lower the score. Higher scores mean closer agreement
with the reference. Grader scores show `—` when the reference has no selected
Graders. Reports also show coverage and precision.

**Case average** gives each scored case equal weight. **Item weighted** gives
larger Specifications more influence. Version comparison shows changes in the
case-average scores.

Detailed reports also compare Behaviour pairs using two text forms: Behaviour
text alone, and Feature–Behaviour–Criterion context. **Mean nearest-neighbour
(NN) similarity** averages each Behaviour's highest similarity to another Behaviour
in the same Specification. Lower means less overlap with the closest neighbours.
Self-comparisons are excluded. A set with fewer than two Behaviours has no NN score.
Reports show each nearest neighbour and the Behaviour count; compare counts when
comparing sets. This score does not measure requirement coverage. Both text forms
are reported, with Behaviour-only text as the starting point for overlap review.
The normal `wizard` run shows reference and generated mean NN scores and Behaviour
counts in an experimental overlap table. Both text versions are saved in `run.json`,
each case's `result.json`, and the run report. NN scores do not set pass/fail status
or contribute to the existing aggregate similarity scores.

Pair similarity shows how similar two Behaviours are. **Difference error** is the average absolute gap
between reference and generated pair similarities; lower is better.

Embeddings are cached beside each Specification YAML and reused while the text,
model, and endpoint remain unchanged. Score reports are saved under `results/` as
Markdown for review and JSON for program use.

There is no similarity pass threshold. Success means completion and scoring for
all four cases. Low similarity scores are findings for prompt and reference review.

### Example output

The CLI shows two tables. This example includes two cases:

```text
                          Wizard evaluation · feat/testbed/wizard-evaluation
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┓
┃ Test Case                ┃ Features ┃ Behaviours ┃ Criteria ┃ Graders ┃ Tasks ┃ Status ┃ Interview ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━┩
│ enterprise-ai-assistant  │    0.708 │      0.409 │    0.520 │       — │ 0.369 │ scored │ done      │
│ billing-support          │    0.281 │      0.185 │    0.179 │       — │ 0.296 │ scored │ done      │
└──────────────────────────┴──────────┴────────────┴──────────┴─────────┴───────┴────────┴───────────┘
                Behaviour overlap · mean NN similarity (experimental)
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓
┃ Test Case                ┃ Text         ┃ Ref count ┃ Gen count ┃ Ref NN ┃ Gen NN ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩
│ enterprise-ai-assistant  │ Behaviour    │ 15        │ 16        │ 0.750  │ 0.799  │
│ enterprise-ai-assistant  │ With context │ 15        │ 16        │ 0.872  │ 0.907  │
│ billing-support          │ Behaviour    │ 2         │ 7         │ 0.729  │ 0.801  │
│ billing-support          │ With context │ 2         │ 7         │ 0.889  │ 0.905  │
└──────────────────────────┴──────────────┴───────────┴───────────┴────────┴────────┘
```

**First table — agreement with the reference.** Higher scores mean closer
agreement. `scored` / `done` means the Interview finished and was scored.
The full output also includes case-average and item-weighted summaries.

**Second table — overlap within each Specification.** `Ref` is the reference;
`Gen` is the generated output. `NN` measures how similar each Behaviour is to its
closest neighbour; lower means less overlap. Compare the counts too.
`With context` adds the Feature and Criteria to the Behaviour text.
High overlap suggests a check for duplicate Behaviours.

## Review cases locally

```bash
uv run python packages/testbed/wizard/reviewer/build.py --serve
```

Open `http://127.0.0.1:8765/.reviewer/`. Generated pages can contain local inputs
and stay Git-ignored.

## Maintain reference cases

`cases/config.yaml` lists the case folders. Each case README records its sources,
scope, and review decisions. Keep reference material outside `inputs/`; only the
prompt and supporting documents go to Wizard. Store generated Specifications in
`results/`, outside the reference outputs.

Review source coverage, assessable Criteria, and Task links. Different wording and
Feature groupings can be valid. Record missing input as unresolved. A human must
review each product Grader before it is treated as approved. Schema validation
alone does not establish reference quality.

Persona metadata is optional and flat. Use `input_style` for communication style;
optional age, occupation, personality, or background values are plain text. Omit
unspecified fields and gender. Scenario metadata can hold `start_prompt` and
`stop_condition`. Engine support for action triggers is planned.

ASSERT-derived cases include source links and MIT licence notices in their case
READMEs. Their inputs and Scenarios are locally authored examples; no ASSERT
pipeline was run. Upstream judge rubrics use `true` for a violation. Keep that
score direction when implementing a Grader.
