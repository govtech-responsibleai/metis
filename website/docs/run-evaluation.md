---
title: Run your evaluations
---

An evaluation has two steps. **Simulate** drives your application with simulated users and
records each conversation. **Evaluate** reads those conversations from Langfuse and runs the
graders.

Before you start, finish the [pre-requisites](prerequisites.md) and
[build your specification](wizard.md).

## Run an evaluation

### Inputs

Put everything the run needs in one folder. The wizard writes it for you.

```text
my-evaluation/
├── specification.yaml
├── target-binding.yaml     # The target connection. The file name is free.
└── fixtures/               # Files that your test cases upload, if any
```

Name the target connection in `specification.yaml` with `target_binding:`. See
[Target connection](target-connection.md) and [Choose the runner](specification-file.md#choose-the-runner).

### Run the commands

Simulate, then evaluate:

```bash
metis engine simulate --input-dir my-evaluation
metis engine evaluate --experiment-dir experiments/execute/<your-run>
```

`simulate` prints the output folder and the `evaluate` command for it. Use the path that it
prints. To do both steps in one command:

```bash
metis engine run --input-dir my-evaluation
```

For the options of each step, see [Run the test suite](run-test-suite.md) and
[Run the graders](run-graders.md).

### Outputs

```text
experiments/execute/<your-run>/
├── inputs/                 # A frozen copy of your specification and fixtures
├── outputs/
│   ├── trials/             # One folder per trial, with its record and artifacts
│   └── reports/
│       └── results.json    # Written by evaluate
└── logs/                   # simulate.log, evaluate.log, and more
```

The folder name comes from the experiment `id` and the start time. A run that only simulated
stops after `outputs/trials/` and `logs/`.

## How the simulation works

### What goes into a Test Case

Your specification holds Test Cases. Each Test Case, a `task` in `specification.yaml`, joins three
things:

| Part | What METIS does with it |
|---|---|
| Persona | A language model plays this user. It types the way the Persona description says, and it gives up when that user would give up. |
| Scenario | The situation and the goal that the simulated user brings to the conversation. |
| Fixtures | The files that the simulated user sends to your application, such as a report. |

<p className="code-caption">
  Personas and Scenarios can also hold <code>metadata</code>: any names and text values, such as
  <code>age</code> or <code>start_prompt</code>. The simulated user receives them as more
  context.
</p>

These make the simulations more realistic, and fit the tests to your use case. The more detail a
Test Case has, the closer the simulations come to how your users act.

Each Test Case can also have trial settings, such as `num_trials`, which sets how many times the
Test Case runs. These settings make the simulation more robust. See
[Write your own specification](specification-file.md#tasks) for all the settings.

### How a Trial runs

In each turn, the simulated user decides on one thing to do, such as to send a message or upload
a file. It follows its Persona and Scenario, as a real user would. A runner carries out that
action on your application through its [API or web UI](expose-an-api-or-web-ui.md). The runner reports what
came back, and the simulated user decides the next step.

Files move in both directions. The simulated user can upload a fixture of its Test Case as a
file. When your application makes a file, such as a chart or a report, the runner collects it
for the simulated user and saves it in the Trial's output folder.

The Trial ends when one of these occurs:

- The simulated user has what the Scenario asks for. If the metadata gives a goal or a success
  condition, the simulated user uses it as a signal.
- The simulated user gives up, as the Persona would.
- The Trial reaches its `max_turns` or `timeout_minutes` limit.

## Next step

[Read your report](report.md).
