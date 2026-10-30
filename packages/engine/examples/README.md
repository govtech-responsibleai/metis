# Examples

Each `http-agentic_eval_toyapp-*` folder here is a ready-to-run experiment input for
`metis engine run`. Each one needs the toy app running, plus user-agent and runner-agent
model credentials. Evaluating a different system requires writing your own specification.
`browser-chat-1/` holds only a template binding, so it is not runnable on its own.

Folder names say how the example runs: `{http|browser}-{target}-{variant}`. The first part
is the generic runner for that transport, driven by a target binding file. `http` calls the
target's API (`HttpRunnerFactory`); `browser` drives its web page (`BrowserRunnerFactory`).
The target is the system under test (`agentic_eval_toyapp`, `chat`). The variant tells apart
different experiments with the same transport and target. It is a number, or a short name
when the name says more, such as `workshop-lite`.

| Folder | What it shows | Runner |
|---|---|---|
| [`http-agentic_eval_toyapp-1/`](http-agentic_eval_toyapp-1/specification.yaml) | The generic HTTP runner on a small app, with an experiment designed in the Wizard's Interview: three Tasks (a concise annual-leave answer, an expense question with missing details, and a question the policy collection cannot answer) put to the [agentic-eval toy app](https://github.com/govtech-responsibleai/agentic-eval-toyapp), and ten LLM-judged Criteria (`CriterionJudgeGrader`) across four Behaviours. It runs one Trial per Task so that a first run is quick. Its binding, [`toyapp-api.yaml`](http-agentic_eval_toyapp-1/toyapp-api.yaml), has no auth and no advice: it names the app and where its OpenAPI document is. Start the app and set `TOYAPP_API_URL` (for example `http://127.0.0.1:8000`) first. | `HttpRunnerFactory` |
| [`http-agentic_eval_toyapp-workshop-comprehensive/`](http-agentic_eval_toyapp-workshop-comprehensive/inputs/specification.yaml) | The full workshop experiment for the toy app: seven Behaviours across three Features (policy answers, report analysis, and request routing), eight Scenarios, three Personas, and eleven Tasks, for 36 Trials. Four Tasks upload a synthetic quarterly report, [`northstar-q2-service-review.md`](http-agentic_eval_toyapp-workshop-comprehensive/inputs/fixtures/northstar-q2-service-review.md), and ask for its findings, for specific figures (one of which the report does not give), about one section in depth, and about a region that the report does not cover. One of them then asks a policy question with the report still attached. The report answers are checked for support by the report, for doing the task that the employee asked for, and for keeping the limitations that the report states. Every Task checks routing with `ActionChoiceAppropriatenessGrader`, which reads the app's recorded choice between answering, clarifying, the policy specialist, and the report specialist. Most Criteria use a library grader. For example, `FactualAccuracyGrader` compares the policy details with a `ground_truth` list in the specification, and `ClaimSupportByEvidenceGrader` checks each claim against the sources in the session (the policy chunks that the app retrieved, or the uploaded report), so it needs no ground truth. The folder keeps the specification and binding in `inputs/`, and a sample [`report.html`](http-agentic_eval_toyapp-workshop-comprehensive/outputs/reports/report.html) in `outputs/reports/`. The sample report grades all 36 Trials with this specification. The policy Trials and the report Trials were simulated in two separate runs. | `HttpRunnerFactory` |
| [`http-agentic_eval_toyapp-workshop-lite/`](http-agentic_eval_toyapp-workshop-lite/inputs/specification.yaml) | A short version of the workshop experiment for a live demo, which runs in about three minutes. It keeps one Behaviour from each Feature of the full experiment, plus a second policy Behaviour, for four Behaviours. Two Scenarios and three Tasks give 6 Trials. In the dog Scenario, the policy collection has no answer and the employee asks for a plain yes or no. AC-2-2 checks that the app follows that instruction, and AC-3-2 checks that it says that the policy does not establish the answer. A reply that gives only a yes or no fails AC-3-2, and a reply that refuses to answer fails AC-2-2. The report Task uploads the same quarterly report as the full experiment, and then asks a policy question. Every Task checks routing. A sample [`report.html`](http-agentic_eval_toyapp-workshop-lite/outputs/reports/report.html) is in `outputs/reports/`. The results of the dog Trials change from run to run, because each run makes new conversations. | `HttpRunnerFactory` |
| [`browser-chat-1/`](browser-chat-1/web-chat.yaml) | A template target binding for a chat app that has only a web page, for the generic browser runner. It has no specification or fixtures: the URL, secret names and sign-in steps in it are made up, so change them for your app. The runner has never met a live page. | `BrowserRunnerFactory` |

## Structure

```
examples/
├── browser-chat-1/
│   └── web-chat.yaml          # a template binding, with no specification
├── http-agentic_eval_toyapp-1/
│   ├── specification.yaml
│   ├── toyapp-api.yaml        # the target binding, beside the specification
│   └── fixtures/
├── http-agentic_eval_toyapp-workshop-comprehensive/
│   ├── inputs/                # specification.yaml, toyapp-api.yaml, fixtures/northstar-q2-service-review.md
│   └── outputs/reports/report.html   # sample report
└── http-agentic_eval_toyapp-workshop-lite/
    ├── inputs/                # specification.yaml, toyapp-api.yaml, fixtures/northstar-q2-service-review.md
    └── outputs/reports/report.html   # sample report
```

The workshop folders keep the experiment input in `inputs/`, so pass that folder as
`--input-dir`.

## Running

From the repository root, with the toy app running and the model credentials set:

```bash
# Simulate, evaluate, and write results.
uv run metis engine run --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/

# Separate phases: simulate prints the evaluate command for the output it wrote.
# The --experiment-dir value is that output directory. Its real name holds the
# experiment id and the start time of the run.
uv run metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/
uv run metis engine evaluate --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/

# A workshop example. The report Tasks upload a file, so run four Trials at a time.
uv run metis engine simulate \
  --input-dir packages/engine/examples/http-agentic_eval_toyapp-workshop-lite/inputs -c 4 -v
```

`run` writes `outputs/reports/results.json` (holding one GraderRecord per grader per session)
under the new `experiments/execute/toyapp-http-simple-<timestamp>/` directory and prints the
`metis insights report` command that builds a report from it.

Simulation uses the live TUI in a terminal. Use `--no-tui` to turn it off. Evaluation uses a
normal progress bar, has no TUI option, and writes one complete `logs/evaluate.log` file in
the named output.

## Binding another API

`http-agentic_eval_toyapp-1/` shows how an experiment uses a target binding. Its
specification names the generic HTTP runner and the binding file next to it:

```yaml
runner_factory_ref: metis.engine.simulation.runners.http.HttpRunnerFactory
target_binding: toyapp-api.yaml
```

The path is relative to the specification and must stay inside the experiment folder, so each
experiment keeps its own copy of the binding. The
[simulation README](../src/metis/engine/simulation/README.md) explains each field and how
to write a binding for your own app. The toy app is the only target the runner has been
tried on. The sample reports in the workshop folders come from runs against the toy app.

See the [engine guide](../../../docs/guide/engine.md) for setup and runner details.
