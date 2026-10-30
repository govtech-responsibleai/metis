# Engine User Guide

## Introduction

metis-engine is the evaluation runtime for METIS. It drives a target through a runner using LLM-powered simulated user personas. Two generic runners drive a target through its API or its web page. It then extracts the resulting traces from Langfuse, runs configurable evaluation graders, and writes their results for [`metis insights report`](insights.md) to turn into a report. Simulation and evaluation are separate commands, with `run` available for the combined flow.

This guide is for anyone setting up evaluations against a web-based agentic system. By the end, you will have:

- A working local installation
- A completed evaluation run using the bundled example experiment
- The knowledge to write your own experiments with custom personas, scenarios, and graders

For the overall METIS architecture and other packages, see the [project README](../../README.md).

---

## Prerequisites & Setup

### Requirements

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (workspace and package manager)
- GNU Make

### Install

From the monorepo root:

```bash
make install          # install everything

make install-engine   # install only engine dependencies (includes Playwright)
```

`make install` installs all workspace dependencies but not Playwright. If you select the browser runner, also install the Playwright extra — `make install-engine` already includes it:

```bash
make install-extras-playwright
```

### Environment Configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Set Langfuse and OpenAI credentials, plus the variables your target binding names:

| Group | Variables | Purpose |
|-------|-----------|---------|
| Langfuse | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | The Langfuse of the system under test. The engine reads the target's traces from it. The engine never traces its own model calls there. |
| METIS-internal Langfuse (optional) | `METIS_INTERNAL_LANGFUSE_PUBLIC_KEY`, `METIS_INTERNAL_LANGFUSE_SECRET_KEY`, `METIS_INTERNAL_LANGFUSE_BASE_URL` | Where the engine and the wizard trace their own model calls. Each trial attempt and each grader run is one trace, and a trial's traces share one session. Tracing is off unless all three are set. |
| Models | `OPENAI_API_KEY`, `OPENAI_BASE_URL` | The shared gateway of the user agent, the runner agent, and the judge. Each role can have its own model and gateway. See the [model guide](models.md). |
| Target binding | for the example, `TOYAPP_API_URL` | The URL, key and login variables that the binding names. See the [simulation README](../../packages/engine/src/metis/engine/simulation/README.md). |

Optional tuning variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `USER_AGENT_MAX_TOKENS` | _(unset)_ | Max tokens per user agent response; unset/empty → parameter omitted, provider default applies. Set explicitly (e.g. `4096`) for reasoning models where chain-of-thought tokens count against the limit |
| `USER_AGENT_TEMPERATURE` | _(unset)_ | Sampling temperature for the user agent; unset/empty → parameter omitted, provider default applies |
| `JUDGE_MAX_INPUT_TOKENS` | `128000` | Largest estimated judge request when the criterion does not set `grader_args.max_input_tokens`. The grader records a larger request as errored and makes no model call. An invalid value logs a warning and uses the default |
| `HEADED` | `false` | Set to `true` to show the browser window |

The [model guide](models.md) lists the model variables of each role, their fallback, and the
Specification fields that record the models. `simulate`, `run`, and `evaluate` check the roles
that they call before the first model call.

### Verify Installation

```bash
metis engine run --help
```

You should see the run command's help text with all available flags.

---

## Quick Start

Run the bundled example experiment to verify everything works end-to-end.

### The Example Experiment

The directory `packages/engine/examples/http-agentic_eval_toyapp-1/` contains a small experiment definition for the bundled toy app. The persona, task descriptions, and grader selection assume that app's API.

```
examples/
└── http-agentic_eval_toyapp-1/   # Three Tasks, one Trial each, no uploaded files
    ├── specification.yaml
    ├── toyapp-api.yaml           # The target binding
    └── fixtures/
```

### Run It

The commands below use `examples/http-agentic_eval_toyapp-1/`, which is small enough for a quick first run.

```bash
metis engine run --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/
```

To run the phases separately, use `simulate` first. It prints the exact `evaluate` command for the output directory it created. `evaluate` scores the directory that you name:

```bash
metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/
metis engine evaluate --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/
```

`experiments/execute/toyapp-http-simple-20260820-143000/` is the output directory that `simulate` created. The name is only a sample: `simulate` makes the real name from the experiment `id` and the start time of the run, so use the path that `simulate` printed.

If simulation stops before all runs finish, continue the output directory that you name. `simulate` prints this exact command, so you never retype a timestamp:

```bash
metis engine simulate --resume --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/
# or run the remaining simulation and then evaluate everything:
metis engine run --resume --experiment-dir experiments/execute/toyapp-http-simple-20260820-143000/
```

Resume reads the experiment and the fixtures from the frozen `inputs/` snapshot in the named directory, not from the source directory. It retries only missing, invalid, or `system_error` records, and appends to the experiment-level simulation log. Extra run folders are ignored. A valid record is complete even if an artifact file is missing. Passing `--resume` with `--input-dir` is an error: the message lists the outputs that exist for the experiment `id` and names the correct flag.

### What You'll See

The engine launches a Simulation TUI for simulation:

- Progress bars for each Task
- Per-run status (`pending → simulating → done/failed`)
- A scrolling log tail with recent events

Evaluation uses a normal, non-full-screen progress bar:

- One completed/total count for run records
- The current record and phase (`extracting` or `evaluating`)
- Failed records advance the bar after the warning is shown

The combined `run` command closes the Simulation TUI before it starts the evaluation progress bar. It performs four phases:

1. **Simulate** — the user agent interacts with the target through the selected runner
2. **Extract** — traces are fetched from Langfuse
3. **Evaluate** — graders score the extracted traces
4. **Results** — grader results are written to `outputs/reports/results.json`; build the report with [`metis insights report`](insights.md)

### Where Results Land

Each execution produces output in `experiments/execute/<id>-<timestamp>/`. The `outputs/reports/` directory is created by `evaluate` or `run`, which write `results.json`; `metis insights report` adds `report.json` and `report.html`. Simulation-only runs stop after `outputs/trials/` and `logs/`:

```text
experiments/execute/toyapp-http-simple-20260730-143022/
├── inputs/
│   ├── specification.yaml
│   └── fixtures/
├── outputs/
│   ├── trials/
│   │   └── TC-001-cooperative-delegator-1/
│   │       ├── record.json
│   │       ├── simulate.log       # Link to the trial log
│   │       ├── evidence/
│   │       │   ├── llm_calls.jsonl  # One row per user-agent and runner-agent LLM request
│   │       │   └── log.jsonl        # One entry per request and response
│   │       └── artifacts/
│   │           ├── run-manifest.json
│   │           └── ...
│   └── reports/
│       ├── results.json           # Engine evaluation
│       ├── report.json            # Insights
│       └── report.html            # Insights
└── logs/
    ├── simulate.log
    ├── simulate-TC-001_cooperative-delegator-01.log
    ├── llm_calls.jsonl            # LLM requests made once per experiment
    └── evaluate.log
```

`results.json` holds one GraderRecord per grader per session, each with one result per grading scope. `metis insights report` reads these records and shows the settings used for each assessment.

The insights [Report model](../../packages/insights/src/metis/insights/_models.py) defines `report.json`. Python readers can validate report data with `Report.model_validate()`.

Use `logs/evaluate.log` to review extraction, each criterion's grader and resolved arguments (including the judge model), every recorded result with its outcome, score and reason, soft failures, hard failures, and final record counts for the latest evaluation attempt.

See the [report contract](report.md) for the report's scoring,
status, failure-evidence, and information-architecture rules.

### Debugging Tip

For the browser runner, set `HEADED=true` to show the browser window. The bundled example selects the HTTP runner. To use the browser runner, set `runner_factory_ref` to `metis.engine.simulation.runners.browser.BrowserRunnerFactory` and supply its credentials:

```bash
HEADED=true metis engine simulate --input-dir packages/engine/examples/http-agentic_eval_toyapp-1/
```

---

## Experiment Configuration

An experiment is defined by a single `specification.yaml` file placed alongside a `fixtures/` directory:

```
my-experiment/
├── specification.yaml
└── fixtures/
    └── my-data.csv
```

### Top-Level Fields

```yaml
schema_version: 1

id: my-evaluation
runner_factory_ref: metis.engine.simulation.runners.http.HttpRunnerFactory
target_binding: toyapp-api.yaml
target:
  name: Employee Policy Assistant
  users: Employees of a fictional company.
  description: Answers employee policy questions from a fixed document collection.
```

| Field | Required | Description |
|-------|----------|-------------|
| `schema_version` | Yes | Always `1` (current version) |
| `id` | Yes | Identifier used in the output directory name |
| `runner_factory_ref` | Yes | Importable RunnerFactory class |
| `target` | Yes | Target name, users, description, and optional detail |
| `features` | Yes for execution | Features, Behaviours, and Criteria to measure |
| `personas` | Yes for execution | User types selected by Tasks |
| `scenarios` | Yes for execution | Situations selected by Tasks |
| `tasks` | Yes for execution | Test Cases with explicit references |
| `fixture_content_descriptions` | No | Map of fixture filenames to content descriptions |

### Personas

Personas are LLM-powered simulated users. During simulation, each persona interacts with the target according to its behavioral profile — communication style, patience level, domain expertise, and goals.

```yaml
personas:
  - id: cooperative-delegator
    name: Cooperative delegator
    description: >
      A mid-level programme manager who is comfortable with AI tools, has time
      to engage, and communicates in a friendly, conversational way. They
      disclose information eagerly and cooperate fully, with a moderate
      frustration threshold.

  - id: impatient-executive
    name: Impatient executive
    description: >
      A time-poor senior director who delegates everything and expects systems
      to just work. They communicate in curt bullet points with no pleasantries
      and have a very low frustration threshold.
    metadata:
      age: In their early fifties.
      input_style: Curt bullet points, no greetings.
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier, referenced by Tasks |
| `name` | Yes | Human-readable Persona name |
| `description` | Yes | Behavioral profile the LLM user agent embodies |
| `metadata` | No | More context for the simulated user, as string keys and string values |

Use `metadata` to add details to the description, such as age or input style. You
choose the keys, and every key is optional. Each value must be a string. The simulated
user receives the details as a list after the description. For the example above, it
sees:

```
- age: In their early fifties.
- input_style: Curt bullet points, no greetings.
```

**Writing effective personas:** Describe observable behaviors. Good descriptions specify communication style (verbose vs. terse), frustration threshold (patient vs. abandons quickly), domain expertise level, and how the persona reacts when things go wrong.

### Scenarios

A Scenario describes the situation and the goal given to the simulated user.

```yaml
scenarios:
  - id: constrained-analysis
    name: Constrained analysis
    description: >
      Upload q3_sales.csv and ask the target to analyse Q3 revenue by region
      using the median, exclude outliers, and produce a report with charts.
    metadata:
      start_prompt: Here are the Q3 sales. Can you break revenue down by region?
      stop_condition: The report has the regional medians and charts.
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier, referenced by Tasks |
| `name` | Yes | Human-readable Scenario name |
| `description` | Yes | What the simulated user will attempt |
| `metadata` | No | More context for the simulated user, as string keys and string values |

Scenario `metadata` follows the same rules as Persona `metadata`. The Engine does not read
any key as a setting. For example, `start_prompt` suggests how the simulated user can open,
and `stop_condition` describes when the user is satisfied. The `max_turns` limit and the
user's own decision still end the conversation.

### Tasks (Test Cases)

Each Task selects one Scenario and one Persona. It also specifies the files,
Trial count, and measured Behaviours for that Test Case. Each selected Behaviour
supplies all its Criteria.

```yaml
tasks:
  - id: TC-001
    scenario_ref: constrained-analysis
    persona_ref: cooperative-delegator
    fixtures: [q3_sales.csv]
    num_trials: 1
    behaviour_refs: [EB-DA-1]
  - id: TC-002
    scenario_ref: constrained-analysis
    persona_ref: impatient-executive
    fixtures: [q3_sales.csv]
    num_trials: 1
    behaviour_refs: [EB-DA-1]
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `id` | Yes | — | Unique Task identifier |
| `scenario_ref` | Yes | — | One Scenario ID |
| `persona_ref` | Yes | — | One Persona ID |
| `fixtures` | No | `[]` | Filenames in `fixtures/` to upload |
| `num_trials` | No | `3` | Number of independent runs; at least `1` |
| `behaviour_refs` | Yes for execution | `[]` | Measured Behaviour IDs. Each selected Behaviour must have Criteria |

**How runs are generated:** Each Task produces `num_trials` independent runs.
The example above produces two runs. Two Tasks can select the same Scenario and
Persona with different fixtures or Behaviours.

Keep Task IDs when you edit or reorder Tasks. Give new and copied Tasks
new IDs. Results and resume checks use the Task ID and Trial index.

Every reference must resolve to an existing ID. IDs must be unique across the
document. Each Scenario needs at least one Task. Each measured Behaviour needs
at least one Criterion and must be selected by a Task. A Task cannot repeat a Behaviour
or fixture reference.

Tasks also accept optional execution settings:

| Field | Default | Purpose |
|-------|---------|---------|
| `max_turns` | `20` | Maximum simulated turns before the run stops |
| `timeout_minutes` | `15` | Time limit for the simulation run |
| `response_wait_ms` | `300000` | Response wait limit used by the runner, in milliseconds |
| `max_run_retries` | `null` | Use the runner's retry default; `0` disables run retries |

The three limits must be positive integers. `max_run_retries` accepts a
nonnegative integer or `null`. A value of `2` allows the initial attempt and
up to two retries. Task settings apply to every Trial of that Task and are
independent of Criterion Grader arguments.

For example, a Task can include:

```yaml
max_turns: 30
timeout_minutes: 20
response_wait_ms: 450000
max_run_retries: 0
```

### Grader References

Each Criterion names a grader class in `grader_fqn` and sets its arguments in `grader_args`,
a mapping whose keys are the fields of the grader's `args_model`. Tasks select Behaviour IDs
through `behaviour_refs`, and each selected Behaviour supplies all its Criteria.

```yaml
criteria:
  - id: AC-DA-1
    name: Finish within the trace budget
    description: A Q3 revenue report session uses no more than 8 exchanges.
    grader_fqn: metis.library.graders.demo.DemoTraceBudgetGrader
    grader_args:
      max_traces: 8
```

`grader_args` is validated before anything runs: an unknown key, a wrong type or a
`threshold` outside 0–1 stops the run and names the Criterion. Use `grader_args: {}` to take
every default. Every grader accepts `threshold` (default 0.5): a scored result passes when its
score is at least the threshold.

For a model-based grader, set the judge model once for the experiment and override it per
Criterion if needed:

```yaml
defaults:
  judge_model: gpt-4o-mini
```

Two Criteria can use the same grader with different arguments; each gets its own results,
identified by its Criterion ID. A trace budget does not change the engine's simulated-turn
limit.

### Working Reference

For a small working example with a persona, scenario, and grader already configured, see [`packages/engine/examples/`](../../packages/engine/examples/) and its [README](../../packages/engine/examples/README.md).

---

## CLI Reference

The engine exposes three commands:

```bash
metis engine simulate --input-dir <source path> [simulation options]
metis engine simulate --resume --experiment-dir <output path> [simulation options]
metis engine evaluate --experiment-dir <output path> [evaluation options]
metis engine run --input-dir <source path> [simulation and evaluation options]
metis engine run --resume --experiment-dir <output path> [simulation and evaluation options]
```

`simulate` writes run records only. It prints the exact command needed to evaluate the output directory it created. `evaluate` scores the output directory that you name, uses its frozen input snapshot, and overwrites `logs/evaluate.log` and `outputs/reports/results.json`, then prints the `metis insights report` command that builds the report. `run` performs both phases.

### Simulation options

`simulate` and `run` work in one of two modes. Give the flags for exactly one mode:

- **New run:** `--input-dir <source>` — the directory with `specification.yaml` and `fixtures/`.
- **Resume:** `--resume --experiment-dir <output>` — an output directory that a previous `simulate` created. Both flags are needed together: `--experiment-dir` without `--resume` is an error, and `--resume` without `--experiment-dir` is an error.

The flags below are optional and apply to both modes:

| Flag | Default | Description |
|------|---------|-------------|
| `--concurrency N` / `-c N` | `1` | Max parallel simulation workers |
| `-v` / `-vv` | WARNING | Increase verbosity: `-v` for INFO, `-vv` for DEBUG |
| `--quiet` | `false` | Suppress all output below ERROR |
| `--no-tui` | `false` | Disable TUI dashboard (force linear log output) |
| `--log-format` | `text` | Log file format: `text` or `json` |
| `--log-dir` | co-located with results | Override the log output directory |

### Evaluation options

| Flag | Default | Description |
|------|---------|-------------|
| `--experiment-dir` | (required) | One output directory that `simulate` created, for example `experiments/execute/toyapp-http-simple-20260820-143000/`. It must hold an `inputs/` snapshot |
| `--langfuse-timeout` | `90` | Seconds to wait for Langfuse traces to appear |
| `-v` / `-vv` | WARNING | Increase evaluation logging verbosity |
| `--quiet` | `false` | Suppress all output below ERROR |

The `run` command accepts the union of the simulation and evaluation options. Its `--no-tui` option controls only the Simulation TUI. Evaluation always uses normal progress output.

### Concurrency

The `--concurrency N` flag runs N simulation workers in parallel. The default is `1`, which runs trials sequentially. Increase based on your target's capacity.

Runs are distributed round-robin across workers. Each worker processes its slice sequentially — one run at a time — while all workers run concurrently via `asyncio.gather`. How isolation and resource sharing work depends on the runner.

#### Browser runner

The factory launches one browser process and signs in once. Each trial gets its own browser context from that signed-in state, so no cookies or pages are shared between workers.

#### HTTP runner

Each worker gets a **fresh `HttpRunner` per trial**, not one for the worker's lifetime. The factory (`HttpRunnerFactory`) mints a new runner for each trial, which goes through `setup` → `act` (repeated) → `end_chat` → `teardown`, then is discarded. Within a trial, turns are strictly sequential: there is no intra-trial parallelism. The factory owns the one HTTP transport that all concurrent runners share.

### Verbosity

| Level | Flag | What you see |
|-------|------|------|
| ERROR only | `--quiet` | Only fatal errors |
| WARNING | (default) | Warnings and errors |
| INFO | `-v` | Operational progress (scenario starts, phase transitions) |
| DEBUG | `-vv` | Full diagnostics (every LLM call, page action, trace fetch) |

The Simulation TUI and evaluation progress are visible regardless of verbosity level in an interactive terminal. Verbosity controls log detail. `--no-tui` changes simulation to linear output; it does not suppress evaluation progress.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `HEADED=true` | Show the browser window (useful for debugging) |

### Interrupt Handling

- **First Ctrl+C:** finishes the current simulated turn gracefully, then stops
- **Second Ctrl+C:** force-aborts immediately

### Non-TTY Environments

The Simulation TUI auto-disables when stderr is not a terminal, such as in CI or when output is piped. Evaluation reports linear per-record progress in this case. Use `--no-tui` if you want linear simulation output in an interactive terminal.

---

## Writing Custom Graders

A grader subclasses `metis.library.grader.Grader`, names an args model, and implements one
async method. It sees only the session's Langfuse traces and the run's artifacts, never the
scenario or persona. The full rules are in the
[grader guide](library/graders.md).

The engine fetches the session and refuses traces it can't support, such as those recorded
before the Langfuse server's v4 upgrade (#469). A grader then reads the session through
`metis.core.trace_processing`, never through an observation's raw `input` or `output`: the
processor knows which payload shapes it can read and returns a `Problem` when it can't, which a
grader records as errored rather than scores. Working examples are in
`metis.library.graders.demo`.

```python
from pydantic import Field

from metis.core.grading import GraderResult, GradingOutput
from metis.core.trace_processing import Problem, select_by_turn, turns
from metis.core.traces import GradingInput
from metis.library.grader import Grader, GraderArgs, LLMSettings


class AnswerLengthArgs(GraderArgs):
    max_chars: int = Field(default=2000, ge=1)


class AnswerLengthGrader(Grader[AnswerLengthArgs]):
    """Every answered turn stays under a character budget."""

    args_model = AnswerLengthArgs

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        selected = select_by_turn(turns(input.traces))
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        results = []
        for label, turn in selected.items():
            if isinstance(turn, Problem) or isinstance(turn[0].reply, Problem):
                detail = (
                    turn.detail if isinstance(turn, Problem) else turn[0].reply.detail
                )
                results.append(
                    GraderResult(status="errored", reason=detail, scope=label)
                )
                continue
            length = len(turn[0].reply)
            results.append(
                GraderResult(
                    status="scored",
                    score=1.0 if length <= self.args.max_chars else 0.0,
                    reason=f"{length} chars",
                    scope=label,
                )
            )
        return GradingOutput(results=results)
```

Put it in any importable module and name it on a Criterion:

```yaml
grader_fqn: my_package.graders.AnswerLengthGrader
grader_args:
  max_chars: 1200
```

A model-based grader's args extend `JudgeArgs` instead; it gets a resolved `self.args.model`
and makes calls through `llm.client`, a shared `AsyncOpenAI`.

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "No traces found" or extraction times out | Langfuse timeout too short, bad credentials, or target not instrumented | Increase `--langfuse-timeout`, verify Langfuse keys in `.env`, confirm your target writes traces to Langfuse |
| "Fixture not found" error | Path is absolute or has a typo | Use the filename only (relative to `fixtures/`), verify the file exists in the fixtures directory |
| "could not be imported" | FQN typo or module not installed | Check the import path for typos, ensure the package containing the grader is installed in your venv |
| Simulation hangs indefinitely | Target unresponsive or page never finishes loading | Use `HEADED=true` to see the browser, increase the Task's `response_wait_ms` |
| Simulation TUI not appearing | Running in a non-TTY environment | Expected — the Simulation TUI requires an interactive terminal. Use linear output or run in a real terminal |
| Ctrl+C doesn't stop immediately | Graceful shutdown is finishing the current simulated turn | Press Ctrl+C a second time to force-abort |
| "is not a subclass of metis.library.grader.Grader" | The FQN names something other than a grader | Subclass metis.library.grader.Grader[YourArgs] and set args_model = YourArgs |
| "has invalid grader_args" | A grader_args key is misspelt, has the wrong type, or is out of range | Fix the field the message names; keys must match the grader's args_model |
| Duplicate persona/scenario ID error | Two entries share the same `id` | Use unique IDs for every persona and scenario |

### Traces recorded before a Langfuse v4 upgrade

METIS can't grade traces recorded before your Langfuse server was upgraded to v4. It detects them automatically and tells you which session is affected. Re-run that trial to grade it.

The affected session is marked failed with a message such as ``Session `sess-…` can't be graded: trace `1c73de62…` was recorded before this Langfuse server's v4 upgrade``. `metis engine evaluate` still grades the other sessions and exits normally.

---

## Adapting to Your Target

The bundled example binds a small app to the generic HTTP runner with a YAML file. Write a custom runner only for a transport that neither generic runner speaks, such as a WebSocket endpoint.

This section covers:
1. Writing a custom `Runner` class
2. Wiring it into the engine via `runner_factory_ref`
3. Understanding the Profile hierarchy
4. The Langfuse requirement for evaluation
5. A minimal experiment template for new targets

### Writing a Custom Runner

The engine interacts with your target through two abstractions:

- **`Runner`** handles a single trial attempt (one persona × one scenario). It carries out one plain-language action per turn on the target and reports what happened.
- **`RunnerFactory`** manages shared resources (connection pools, browser instances) and creates fresh `Runner` instances per attempt.

The normative rules every runner must satisfy are in the [runner contract](../runner-contract.md).

#### The Runner ABC

Source: `packages/engine/src/metis/engine/simulation/runner.py`

```python
class Runner(ABC):
    ledger: ArtifactLedger  # bound by the orchestrator before setup()

    @property
    @abstractmethod
    def session_id(self) -> str | None:
        """The target's session ID, copied by code from a submission's answer."""

    @abstractmethod
    async def setup(self, config: TrialConfig) -> None:
        """Prepare the connection. `config` carries the trial's budget and deadline."""

    @abstractmethod
    async def act(self, action: str, promised: list[Promise]) -> Observation:
        """Carry out one plain-language action and report what happened."""

    @abstractmethod
    async def end_chat(self, promised: list[Promise]) -> None:
        """The closing step: collect what the target made available. Not a turn."""

    @abstractmethod
    async def teardown(self) -> None:
        """Release what `setup` acquired."""
```

The orchestrator calls `setup()` once, then `act()` once per turn until the user agent stops, then `end_chat()` for a healthy ending, then `teardown()` even on failure. The user agent writes each action in plain language. Text meant for the target sits between `⟦` and `⟧`, and a runner sends those spans word for word.

#### Key Types

These Pydantic models are defined in `metis.engine.simulation.types`:

```python
class Reading(BaseModel):
    outcome: str  # What the runner thinks happened
    why: str
    next_options: str = ""  # What the user could do next, if the runner has a view


class Observation(BaseModel):
    reply: str | None  # The target's reply, copied by code. None when none was shown
    reading: Reading  # The runner's own interpretation, kept apart from the facts
    promised: list[str] = []  # Names of files the reply promised
    observed: bool = True  # False when nobody could check the target after the action
    notice: str | None = None  # A problem METIS itself found with the turn
    submission_unresolved: bool = False  # A submission never settled
    sent_nothing: bool = False  # The action quoted no message, so nothing was sent
```

Facts and interpretation stay apart: `reply` and `promised` are copied by code from what the transport recorded, and only `reading` holds the runner's opinion, which the user agent is told is an interpretation. A runner records every file it sends or receives through `self.ledger` (`record_upload`, `record_download`, `record_failure`).

#### The RunnerFactory Protocol

```python
class RunnerFactory(Protocol):
    async def start(self) -> None:
        """Acquire shared resources (open connection pool, launch browser)."""

    async def create(
        self, run_dir: Path, fixtures_dir: Path, experiment_root: Path
    ) -> Runner:
        """Create a fresh Runner for one attempt."""

    async def close(self) -> None:
        """Release shared resources."""
```

The engine also expects a `retry_defaults` property that returns `(trial_max_retries, trial_retry_delay_seconds)`. It builds your factory with `factory_cls()`, or, when the class has a `from_specification(specification, inputs_dir)` classmethod, with the specification and the experiment's `inputs/` folder. `HttpRunnerFactory` and `BrowserRunnerFactory` use the second form to load their target binding.

#### A Minimal Runner

A runner for a target with one chat endpoint:

```python
"""A runner for a target with a single JSON chat endpoint."""

from __future__ import annotations

import httpx

from metis.engine.simulation.runner import Runner
from metis.engine.simulation.types import Observation, Promise, Reading
from metis.engine.simulation.runners.spans import Spans


class ChatRunner(Runner):
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None
        self._session: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session

    async def setup(self, config) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=60)

    async def act(self, action: str, promised: list[Promise]) -> Observation:
        assert self._client is not None
        spans = Spans.of(action)
        if not spans.texts:
            return Observation(
                reply=None,
                reading=Reading(
                    outcome="not_sent", why="The action quoted no message."
                ),
                sent_nothing=True,
            )
        response = await self._client.post("/chat", json={"message": spans.texts[0]})
        response.raise_for_status()
        data = response.json()
        self._session = data.get("session_id", self._session)
        return Observation(
            reply=data.get("reply"),
            reading=Reading(outcome="replied", why="The target answered."),
        )

    async def end_chat(self, promised: list[Promise]) -> None:
        pass

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()


class ChatRunnerFactory:
    def __init__(self) -> None:
        import os

        self._base_url = os.environ["TARGET_API_URL"]

    @property
    def retry_defaults(self) -> tuple[int, float]:
        return (2, 5.0)

    async def start(self) -> None:
        pass

    async def create(self, run_dir, fixtures_dir, experiment_root) -> ChatRunner:
        return ChatRunner(self._base_url)

    async def close(self) -> None:
        pass
```

#### Implementation Prerequisites

Before writing your runner:

1. **Understand the turn loop.** The engine calls `setup()` once, then `act()` once per turn until the user agent decides to stop, then `teardown()`. Your runner must keep a conversation session across turns.

2. **Handle fixtures through the ledger.** When a Task lists fixture files, the trial holds them already. A runner that uploads one records it with `self.ledger.record_upload`. A fixture that is never uploaded ends the trial as `system_error`.

3. **Return a session ID.** The engine uses it for Langfuse trace extraction in the evaluation phase. If your target does not use Langfuse, return `None`, but evaluation will then be unavailable (see [Langfuse Requirement](#langfuse-requirement)).

### Wiring Your Runner into the Engine

Once you have a `RunnerFactory` class, tell the engine to use it via the `runner_factory_ref` field in `specification.yaml`.

#### The `runner_factory_ref` Field

Add `runner_factory_ref` at the top level of your experiment configuration. This
excerpt selects the REST runner and defines one Test Case:

```yaml
schema_version: 1
id: my-api-eval
runner_factory_ref: my_package.runners.RestRunnerFactory

personas:
  - id: cooperative
    name: Cooperative user
    description: A friendly, patient user.

scenarios:
  - id: basic-chat
    name: Basic chat
    description: Ask a simple question and verify the response.

tasks:
  - id: TC-001
    scenario_ref: basic-chat
    persona_ref: cooperative
    fixtures: []
    num_trials: 1
    behaviour_refs: [EB-CHAT-1]
```

Include the Target and Feature hierarchy as well. The
[minimal template](#minimal-template) shows the complete document and defines
Criterion `AC-CHAT-1`.

The value is a fully-qualified Python name pointing to your `RunnerFactory` class. The engine resolves it at load time using `importlib.import_module` — if the import fails or the class lacks `start`, `create`, or `close` methods, validation raises an error immediately.

`runner_factory_ref` defaults to `metis.engine.simulation.runners.http.HttpRunnerFactory`. A browser target names `metis.engine.simulation.runners.browser.BrowserRunnerFactory`, and a custom runner names its own factory.

#### Resolution Logic

Source: `packages/engine/src/metis/engine/simulation/runner_resolver.py`

The engine performs these checks at experiment load time:

1. Split `runner_factory_ref` on the last `.` to get `(module_path, class_name)`
2. Import `module_path` — raises `ImportError` if not found
3. Get `class_name` from the module — raises `ImportError` if the attribute doesn't exist
4. Verify the class has callable `start`, `create`, and `close` methods — raises `TypeError` if any are missing

At simulation time (`packages/engine/src/metis/engine/cli.py:557-563`):

```python
factory_cls = resolve_runner_factory(experiment.runner_factory_ref)
runner_factory = factory_cls()
```

The engine calls your factory's constructor with no arguments. All configuration (credentials, URLs, feature flags) should come from environment variables read inside `__init__`.

#### Removing Playwright Dependencies

If your target is not browser-based:

1. **Playwright is optional.** A runner that does not use a browser does not need the Playwright extra.

2. **Set the variables for the selected runner.** A generic runner reads the variables its target binding names. A custom runner reads its own.

3. **Your `.env` only needs your own variables** plus the ones required by the engine core:
   - `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` — needed if you want evaluation (trace extraction)
   - `OPENAI_API_KEY` — needed for the simulated user agent and LLM-judge graders
   - Any variables your own factory reads in `__init__()`

#### Installability Requirement

Your runner module must be importable from the environment where `metis engine simulate` runs. Options:

- **In-tree:** Place your runner under `packages/engine/src/metis/engine/simulation/runners/` and use the FQN `metis.engine.simulation.runners.myrunner.MyRunnerFactory`
- **External package:** Install your package into the same venv (`uv pip install ./my-runner-pkg`) and reference its FQN
- **Single file:** Place a `.py` file anywhere on `PYTHONPATH` and reference it

### Profile Configuration (specification.yaml)

The Profile contains Target context and the Feature, Behaviour, and Criterion
hierarchy, including Grader settings. The Experiment configuration contains Personas, Scenarios,
Tasks, the experiment ID, and the runner reference. The Specification combines
the Profile and Experiment configuration.
`specification.yaml` stores all these fields at the top level.

#### Relationship to the Specification

| Concern | Fields in `specification.yaml` | Purpose |
|---------|--------------------------------|---------|
| Simulation setup | `id`, `runner_factory_ref`, `personas`, `scenarios`, `tasks` | Select the runner and define each Test Case and its Trials |
| Evaluation requirements (Profile) | `target`, `features` | Describe the target, expected Behaviours, Criteria, and Grader settings |

Tasks select measured Behaviours from the Profile. Reports combine the planned Tasks and
recorded results to show whether the target meets those Criteria.

The engine freezes the document under the output directory's `inputs/` directory.
Reporting reads this copy and joins scores by Criterion ID. The report retains
the grader configuration used for each Criterion.

#### Schema Reference

The [JSON Schema](../../packages/core/schemas/specification.schema.json) provides
editor completion and shape validation. The engine also checks references and
coverage when it loads the document. From a specification in
`packages/engine/examples/http-agentic_eval_toyapp-1/`, use this editor directive:

```yaml
# yaml-language-server: $schema=../../../core/schemas/specification.schema.json
```

```yaml
schema_version: 1
id: <string>              # Experiment identifier
runner_factory_ref: <string>  # Importable RunnerFactory class
target:
  name: <string>           # Target name
  users: <string>          # Prose that describes the target users
  description: <string>    # Short description of what is evaluated
  detail: <string>         # Longer context about the evaluation scope

features:
  - id: <string>           # Unique feature identifier (e.g. "EP-3")
    name: <string>         # Human-readable feature name (e.g. "Data Analyst")
    description: <string>  # What the feature must achieve
    behaviours:
      - id: <string>       # Unique behaviour identifier (e.g. "EB-DA-1")
        name: <string>     # Human-readable behaviour name
        description: <string>       # Full behavioural description
        measured: <bool>            # Whether the evaluation measures this behaviour
        criteria:
          - id: <string>            # Acceptance criterion ID (e.g. "AC-DA-20a")
            name: <string>          # Human-readable criterion name
            description: <string>  # One non-empty assessment rule
            grader_fqn: <string>
            grader_args: {}         # Grader constructor arguments

personas:
  - id: <string>
    name: <string>
    description: <string>

scenarios:
  - id: <string>
    name: <string>
    description: <string>

tasks:
  - id: <string>
    scenario_ref: <scenario-id>
    persona_ref: <persona-id>
    behaviour_refs: [<behaviour-id>]
    fixtures: [<filename>]
    num_trials: <integer>
```

#### Field Descriptions

**`schema_version`** — the specification schema version. The current version is `1`. The engine requires this field and rejects an unsupported version.

**`target`** — top-level metadata:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Name of the target being evaluated |
| `users` | Yes | Prose that describes who uses the target |
| `description` | Yes | Short evaluation description |
| `detail` | No | Extended context about the evaluation's purpose and scope |

**`features[]`** — target functions or user workflows being evaluated:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Identifier (new wizard features use `F-N`) |
| `name` | Yes | Human-readable name |
| `description` | Yes | What the feature must achieve |
| `behaviours` | No | Expected behaviours; defaults to `[]` |

**`features[].behaviours[]`** — observable behaviors:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Identifier (conventionally `EB-<FEATURE>-N`) |
| `name` | Yes | Human-readable behaviour name |
| `description` | Yes | Full description of what the target must do |
| `measured` | No | `true` when the evaluation measures this behaviour; defaults to `false` |
| `criteria` | No | Acceptance criteria; defaults to `[]`. Measured Behaviours need Task coverage |

**`features[].behaviours[].criteria[]`** — assessment Criteria:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Identifier (conventionally `AC-<FEATURE>-N`) |
| `name` | Yes | Human-readable criterion name |
| `description` | Yes | Non-empty text that states one assessable requirement, including any necessary condition |
| `grader_fqn` | Yes for execution | Fully-qualified grader class name; drafts can use `null` |
| `grader_args` | No | Constructor arguments; defaults to `{}` |

#### Minimal Example

This Profile excerpt defines a turn-budget requirement for a chatbot:

```yaml
target:
  name: My Chatbot
  users: People who need concise answers.
  description: Evaluate the number of turns used for direct questions.
  detail: Tests direct questions from cooperative users.

features:
  - id: EP-1
    name: General Chat
    description: Answer direct questions.
    behaviours:
      - id: EB-CHAT-1
        name: Keep conversations short
        description: Answer direct questions within a small turn budget.
        measured: true
        criteria:
          - id: AC-CHAT-1
            name: Short turn budget
            description: A session for a factual question uses no more than 4 exchanges.
            grader_fqn: metis.library.graders.demo.DemoTraceBudgetGrader
            grader_args:
              max_traces: 4
```

Add the experiment ID, runner, Personas, Scenarios, and Tasks to make a complete
Specification. The [minimal template](#minimal-template) below shows these fields
together. Use `measured: true` for Behaviours selected by Tasks. Unmeasured
Behaviours and their Criteria can remain in the document. Every Criterion needs
a grader before the engine can load the specification.

### Langfuse Requirement

The `evaluate` command requires that your target writes traces to [Langfuse](https://langfuse.com). The engine uses the session ID in `Runner.session_id` to fetch traces from Langfuse, then feeds them to your configured graders.

#### What This Means in Practice

| Phase | Langfuse needed? | What happens without it |
|-------|-----------------|------------------------|
| `simulate` | No | Simulation runs normally — the engine drives your target and writes trial records and logs |
| `evaluate` | **Yes** | Extraction fails — no traces to score. Graders receive empty inputs. |
| `run` (combined) | **Yes** (for eval) | Simulation succeeds, evaluation fails at the extraction step |

#### Simulation-Only Fallback

If your target does not instrument with Langfuse, you can still use METIS for simulation:

```bash
# Run simulation only — no trace extraction needed
metis engine simulate --input-dir my-experiment/
```

This produces trial records in `experiments/execute/<id>-<timestamp>/outputs/trials/`. You get:
- Outcome data (stop reason, turn count, duration)
- Collected artifacts
- The trial's `logs/`, which record each turn's message and response as plain text

You lose:
- A structured conversation transcript (METIS reads the conversation from Langfuse; trial records
  do not hold a copy)
- Grader scoring (requires traces)
- The structured HTML/JSON report
- Per-turn internal reasoning visible in traces

#### Adding Langfuse to Your Target

If you want evaluation, instrument your target with the Langfuse SDK:

1. Add `langfuse` to your target's dependencies
2. Wrap your LLM calls with Langfuse's `@observe` decorator or use the callback handler
3. Ensure each conversation session gets a consistent `session_id`
4. Return that `session_id` from your runner's `session_id` property

The engine then fetches traces using:
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL` from your `.env`
- The session ID from the run record
- A configurable timeout (`--langfuse-timeout`, default 90s) for traces to appear

### Writing Your Own Experiment

Use this template and checklist when creating an experiment from scratch for a new target.

#### Minimal Template

Save this as `my-experiment/specification.yaml`. Set `runner_factory_ref` to your installed factory.

```yaml
schema_version: 1
id: my-target-eval
runner_factory_ref: my_package.runners.MyRunnerFactory

target:
  name: My Chatbot
  users: People who need concise answers.
  description: Evaluate the number of turns used for direct questions.

features:
  - id: EP-1
    name: General Chat
    description: Answer direct questions.
    behaviours:
      - id: EB-CHAT-1
        name: Keep conversations short
        description: Answer direct questions within a small turn budget.
        measured: true
        criteria:
          - id: AC-CHAT-1
            name: Short turn budget
            description: A session for a factual question uses no more than 4 exchanges.
            grader_fqn: metis.library.graders.demo.DemoTraceBudgetGrader
            grader_args:
              max_traces: 4

personas:
  - id: cooperative
    name: Cooperative user
    description: A patient user who gives requested details.

scenarios:
  - id: smoke-test
    name: Direct factual question
    description: Ask for the difference between a bar chart and a histogram.

tasks:
  - id: TC-001
    scenario_ref: smoke-test
    persona_ref: cooperative
    fixtures: []
    num_trials: 1
    behaviour_refs: [EB-CHAT-1]
```

#### Pre-Flight Checklist

Before running `metis engine simulate --input-dir my-experiment/`:

- [ ] **Runner accessible:** Your `RunnerFactory` class is importable from the current venv.
  ```bash
  python -c "from my_package.runners import MyRunnerFactory"
  ```

- [ ] **Environment variables set:** All variables your factory's `__init__()` reads are in `.env` or exported.
  ```bash
  # For custom runners: whatever your factory needs
  # For evaluation: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
  # For user agent / judge graders: OPENAI_API_KEY
  ```

- [ ] **Fixtures exist:** Every filename in a Task's `fixtures:` list exists in `my-experiment/fixtures/`.

- [ ] **References match:** Each Task selects an existing Scenario, Persona, and measured Behaviours. Every Scenario and measured Behaviour has Task coverage.

- [ ] **Graders importable:** Every Criterion's `grader_fqn` resolves to an installed class.
  ```bash
  python -c "from metis.library.graders.demo import DemoTraceBudgetGrader"
  ```

- [ ] **Dry-run validation:** Load the experiment to catch schema errors early:
  ```bash
  python -c "
  from pathlib import Path
  from metis.engine.simulation.types import Specification
  Specification.load_file(Path('my-experiment/specification.yaml'))
  "
  ```

#### Adding Complexity Incrementally

Start with the minimal template above, verify it runs end-to-end, then layer in complexity:

1. **Add fixtures** — put files in `fixtures/`, reference them in `tasks[].fixtures`, and ensure your runner records each upload in the ledger
2. **Add personas** — write 2-3 personas with contrasting behavioral profiles, select each one in a Task through `persona_ref`
3. **Add graders** — start with code-graded graders (fast, deterministic), then add judge-graded graders
4. **Extend coverage** — define more Features, Behaviours, and Criteria, then select the Behaviours in Tasks
5. **Tune parameters** — adjust Criterion `grader_args` and Task `num_trials` based on observed runs
