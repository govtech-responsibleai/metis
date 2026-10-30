# Simulation Framework

LLM-driven persona simulation for end-to-end testing of an AI assistant. Drives real conversations through a target via a pluggable runner and writes frozen run records for later evaluation.

## Architecture

```
CLI (sync) → run_experiment() → asyncio.run()
  └── RunnerFactory.start()
       ├── Worker 0: factory.create() → Runner → run slice
       ├── Worker 1: factory.create() → Runner → run slice
       └── ... (N workers, set by --concurrency)
```

```
User Agent (Python/AsyncOpenAI)  →  Runner  →  Target
```

- **User Agent** — embodies the persona, generates next messages; imported and called directly by the orchestrator. Its system prompt gives each persona and scenario description, then any `metadata` entries as `- key: value` lines, with keys as the author wrote them. No metadata key is an Engine setting: `start_prompt` or `stop_condition` is context for the simulated user only.
- **Runner** — translates messages and actions into transport-specific calls (HTTP API, browser automation, etc.) and returns observations
- **RunnerFactory** — manages shared resources (connection pools, browser instances, rate limiters) and creates fresh `Runner` instances per attempt

### Built-in runners

Two generic runners ship with the engine. Each is driven by a *target binding* file and needs no code per app; see [The generic runners](#the-generic-runners).

| Runner | Transport | Notes |
|--------|-----------|-------|
| `HttpRunner` | HTTP | Calls the target's REST API, guided by its OpenAPI document. |
| `BrowserRunner` | Playwright (browser) | Drives the target's web page in headless Chromium. Needs the `playwright` extra. |

Both satisfy the normative [runner contract](../../../../../../docs/runner-contract.md); a custom runner must too.

Custom runners are selected via `runner_factory_ref` in `specification.yaml`. See the [Engine User Guide](../../../../../../docs/guide/engine.md#writing-a-custom-runner) for the `Runner` ABC, `RunnerFactory` protocol, and a complete REST example.

### Concurrency

Workers run concurrently via `asyncio.gather`. Each worker processes its slice of runs sequentially, creating a fresh `Runner` per run. How isolation and shared resources work is runner-specific — see the [Concurrency section](../../../../../../docs/guide/engine.md#concurrency) in the user guide.

### Artifacts

Charts (screenshotted as PNG) and downloads are captured and stored under the target session ID, which matches the Langfuse `session_id` for trace linking.

### Actions and uploads

Each turn the user agent emits one plain-language action; the orchestrator passes it to `Runner.act(action, promised)`, and the runner works out how to carry it out. A scenario's fixtures are held by the trial's `ArtifactLedger` from the start, and a runner records each upload with `record_upload`. A trial whose scenario names a fixture that was never uploaded ends as `system_error` with the failure `fixture_never_uploaded`.

If the target says "please wait until next turn," that stays natural-language text in the observation. Nothing mechanically blocks an upload: the user agent is trusted to read the cue and hold the action.

### LLM-call log

Every simulation LLM call goes through `llm_calls.parse_completion`, which writes one row per request to an `LLMCallLog`: a trial's calls to `outputs/trials/<id>/evidence/llm_calls.jsonl`, and calls made once per experiment (fixture descriptions) to `logs/llm_calls.jsonl`. Each row records the component, the requested and returned model, tokens in and out (`null` when the endpoint did not report them), latency, and any error. The wrapper retries failed requests itself, so a new caller must build its `AsyncOpenAI` client with `max_retries=0` to keep every attempt in the log.

The same wrapper names the METIS-internal Langfuse on every request, so each attempt is also traced there as a generation named by its component. Each trial attempt is one trace, in a Langfuse session that the trial's grading traces share. Tracing is off unless the three `METIS_INTERNAL_LANGFUSE_*` variables are set, and it never goes to the target's `LANGFUSE_*` project. Build the client with `model_settings.llm_client`, which returns the `langfuse.openai` drop-in.

### Transport log

`transport_log.LoggingTransport` wraps an `httpx` transport and writes every request and the response that answers it to `outputs/trials/<id>/evidence/log.jsonl`, so a retry loop above it gets one pair of entries per attempt with no help. Each entry has an ID, a kind (`request` or `response`), a role (`action` or `result`), the request it answers, a one-line summary written by code, redacted headers and a body. `Authorization` and each header named in the target binding's `secret_headers` are written as `***`; only header names are redacted, so a secret placed in a URL or body would be logged as sent. A body over 64 KB goes to `evidence/<id>.bin`, and a downloaded artifact is logged as an `ArtifactRef` (its path and SHA-256) instead of a copy.

`artifacts.ArtifactLedger` is the one place a runner records a file, as METIS's own `Artifact`. `record_download` saves the body under the last component of the target's name in `<trial>/artifacts/`, writing `<name>.part` and renaming it only once the bytes are whole and checked, so a partial download is never kept. A name that is taken becomes `name-1.ext`, `name-2.ext`; nothing already saved is overwritten and no entry is ever replaced. It returns the transport log's `ArtifactRef`. The byte check refuses a `.png`, `.jpg`, `.gif`, `.pdf`, `.docx`, `.xlsx`, `.pptx` or `.zip` that does not start with its type's signature, and any JSON document or JSON content type saved under a name that is not `.json`; a refused download leaves no file and no entry. A fixture has one entry however often it is uploaded: `record_upload` stamps the first upload's turn on it and adds nothing. The caller supplies `at_simulated_turn`. Each entry's `content_description` is one facts line written by code, never the file's content: name, type and size, and for a CSV its data rows, columns and header. Facts are computed once per distinct digest.

A `Runner` is `setup`, `act(action, promised)`, `end_chat(promised)` and `teardown`; the orchestrator owns the trial's `ArtifactLedger` and binds it to the runner with `use_ledger` before `setup`, so every file a runner records lands in the one record. `act` is called once per turn and the runner's own count of calls is the turn's `at_simulated_turn`, from 1. The closing `end_chat` runs after goal, abandonment, `max_turns` or `timeout`, but not after `interrupted`, `target_exhausted` or `system_error`, and it is not a turn. A `TurnRecoverableError` or `ResponseTimeoutError` from `act` becomes an undelivered `Observation` the user agent is told about, and a second one in a row raises `ConsecutiveFailureEscalation`. Fixtures are described by `file_facts`, with no LLM call. A factory that needs the specification defines `from_specification(specification, inputs_dir)`. `HttpRunnerFactory` uses it to load the specification's `target_binding` from the experiment's `inputs/`, so a binding must sit inside the input folder.

## The generic runners

The generic HTTP runner lets you bind an app that has an OpenAPI specification with a YAML
file, a *target binding*, instead of writing a Python runner. A browser runner does the same
for an app that has only a web page. In both, a user agent decides one plain-language action
per turn, and a runner carries it out on the target.

> **Tested on the bundled toy app only.** The rules below were each found while binding
> an app, and a second app will probably need more. Once a second app has been bound, this
> page becomes the basis for the user guide.

### How a turn works

```
user agent ──action──▶ HttpRunner.act ──▶ runner agent (LLM) ──tool calls──▶ target
 "Ask ⟦hi⟧"               │                    │                             │
                          │                    └── http_request, poll_until, fetch_files,
                          │                        session_id_from, note, report
                          ▼
                    Observation  ◀── built by code from what the transport log recorded
```

1. The user agent writes one action. Text meant for the target sits between `⟦` and `⟧`.
2. `act` numbers those spans `{{1}}`, `{{2}}`, ... and settles any submission left open by
   an earlier action.
3. The runner agent, an LLM, is shown an index of the target's OpenAPI specification
   (fetched once per trial), reads an endpoint's definition with `operation` when it needs
   it, and calls tools until it calls `report`. Results from earlier rounds are shortened
   to the log entry that holds them. It is limited to 12 rounds and to
   `response_wait_ms` plus 60 seconds, and never goes past the trial deadline.
4. Code builds the `Observation`. The agent's own words fill only `reading`
   (`outcome`, `why`, `next_options`), which the user agent is told is an interpretation.

Every request and response goes to `outputs/trials/<id>/evidence/log.jsonl`, and every LLM
call to `evidence/llm_calls.jsonl`.

### The rules code enforces, and why

Each rule answers something an LLM did that looked reasonable and was wrong. Code
enforces them; the prompt only explains them.

| Rule | Why |
| --- | --- |
| A path is absolute, as the specification writes it, with no `//`, `..`, `?` or `#`. | A path can otherwise leave the API or smuggle a query. |
| `forbidden_calls` in the binding are refused before anything is sent. | The agent chose a plausible call, such as a delete, that the owner never wants made. |
| The agent cannot set `Authorization`, `Cookie` or `Host`. Code adds credentials. | The agent must never see or send a secret, and the log redacts them. |
| The user's words reach the target only as `{{n}}` placeholders that code replaces. | The record can then say the target received the user's words exactly. |
| A submission is refused when the action quoted nothing. | The agent invented a message the user never wrote. |
| An action whose submission was refused for quoting nothing is not a turn; three in a row end the trial. | The user agent is told, and the turn count and `max_turns` stay true. |
| One submission may be open at a time; `poll_until` settles it. | A second message sent while the first is running corrupts the conversation. |
| The session ID is copied from a submission's reply, and nowhere else. | The agent once pointed at an upload's file ID. |
| `fetch_files` takes a logged listing that is this conversation's, at most 100 files, and one `{id}` in the path. It skips the user's own uploads and files already held. | An account-wide listing would pull in files from other conversations. |
| A reply or promised file may be cited only from entries logged during this action. | An earlier action's reply would otherwise be reported as this one's. |
| A promised name must be a single line. | A whole page of text is not a file name. |
| A 429 is waited out (up to 3 resends, honouring `Retry-After`) while the trial has time. | Rate limits are the target's, not a failure. |

A refusal goes back to the agent as `{"error": "refused, nothing was sent: ..."}`, so it
can try something else. Nothing here raises for the agent's mistakes.

`observed` is `False` when a submission is still open or a call failed at the transport.
`notice` carries a problem METIS itself found: a poll the target answered with a 4xx, an
open submission, a transport failure, the time limit or the round cap.

### Writing a target binding for a new app

The binding is a YAML file inside the experiment's `inputs/` folder, named from
`specification.yaml`:

```yaml
runner_factory_ref: metis.engine.simulation.runners.http.HttpRunnerFactory
target_binding: my-app.yaml
```

Its shape is `TargetBinding` in `metis.core.target_binding`, published as
`packages/core/schemas/target-binding.schema.json`. Start from the example below and
change these:

- `identity` names the app.
- `spec_url` is where the OpenAPI document lives. `${NAME}` is read from the environment.
  The runner joins each path to the specification's first server URL, so patterns and
  paths are written *relative to that server*: if the document's server is `/`, a chat call is
  `/api/v1/chat`; if it is `/api/v1`, the same call is `/chat`.
- `auth.secret_env` names the environment variable holding the credential, sent as the
  scheme the specification declares. Secrets are never written in the file.
- `secret_headers` adds a header from an environment variable to matching calls. A secret
  that is not set adds nothing.
- `submissions` lists the calls that send the user's message. Left empty, any `POST`,
  `PUT` or `PATCH` with a JSON body counts. The Wizard's connection test suggests entries
  from the OpenAPI document and warns about an entry that matches no call. The engine reads
  only this list and infers nothing at run time.
- `forbidden_calls` are `METHOD /glob` patterns; `*` matches within a path segment and
  `**` across segments. Write `*` for a path parameter.
- `advice` (`limits`, `notes`) is for the agent only. Code does not check it. Put in it
  what the specification cannot say, such as "the first chat call starts the session".

The example, `packages/engine/examples/http-agentic_eval_toyapp-1/toyapp-api.yaml`:

```yaml
# yaml-language-server: $schema=../../../core/schemas/target-binding.schema.json
# The agentic-eval toy app's REST API, bound to the generic HTTP runner. Its OpenAPI
# document declares no server URL, so paths are written from the host root.
schema_version: 1
identity: {name: Agentic Eval Toy App}
transport: http
spec_url: ${TOYAPP_API_URL}/openapi.json  # TOYAPP_API_URL is the host, e.g. http://127.0.0.1:8000
# The app has no authentication, so there is no auth block.
# A message goes to an open session, so opening one (POST /sessions) is not the user's message.
submissions: ["POST /api/v1/sessions/*/messages"]
```

To try a binding, set the variables it names and run the experiment as usual. The runner
agent is its own model role. See the [model guide](../../../../../../docs/guide/models.md).

### The browser runner, for an app with only a web page

> **Never run against a live page.** `BrowserRunner` has been tested on a fake page and on
> a static page in headless Chromium, and on nothing else. Expect the first real app to
> need changes.

A browser binding has `transport: browser` and a `start_url` instead of `spec_url`; it
takes no `auth`, `secret_headers`, `submissions`, `forbidden_calls` or `preflight_reads`.
Point `runner_factory_ref` at
`metis.engine.simulation.runners.browser.BrowserRunnerFactory`.

- `login.note` says in plain words how to sign in, and `login.secrets` names the
  environment variables holding what it types. The note writes `{{secret:NAME}}` where a
  secret goes. The factory's `start()` has the runner agent sign in once; code types the
  secret, and the log shows `***`. The logged-in state is kept in memory, never written,
  and each trial starts from it.
- The agent sees the page as an accessibility snapshot, one element per line, and acts by
  `ref` (`snapshot`, `click`, `type`, `choose`, `choose_file`, `wait_for`, `fetch_files`).
  Code refuses a choice the user did not name, and any text typed when the action quoted
  none. A message counts as sent when the text leaves its field, and the submission stays
  open until `wait_for` settles it.
- Each action is a `request` in the transport log and each capture of the page a `response`
  whose body is `{url, title, snapshot}`. `report` cites an element of a capture with
  `ref`, and the session ID with `at: $.url` and a `pattern`.
- Files go through the ledger as for HTTP: downloads with `record_download`, uploads with
  `record_upload`, recorded only when the page then shows the file's name.
- `end_chat` does nothing: a page has no list of a session's files to collect afterwards.
- The loop in `runners/browser.py` is a copy of `HttpRunner`'s, and its prompt a copy of the
  frame of the HTTP one. Stage 4 merges them into a shared base.

The example, `packages/engine/examples/browser-chat-1/web-chat.yaml`. Its URL, secret
names and sign-in steps are made up:

```yaml
# yaml-language-server: $schema=../../../core/schemas/target-binding.schema.json
# A chat app that has only a web page, bound to the generic browser runner. The runner
# has never met a live page, and this file is a template to change: the URL, the secret
# names and the sign-in steps are made up.
schema_version: 1
identity: {name: Example web chat}
transport: browser
start_url: ${CHAT_URL}
login:
  note: >-
    Sign in on the start page: type {{secret:CHAT_USER}} in the email box and
    {{secret:CHAT_PASSWORD}} in the password box, then press Sign in.
  secrets: [CHAT_USER, CHAT_PASSWORD]
advice:
  notes: |
    Type the message in the chat box and press Send. Wait until the reply has finished
    before acting again. Attach files with the attach control before sending.
```

### Not covered yet

Trimming what is resent to the LLM each round (#482). The closing step that collects files
after the conversation, and the record checks (#483); `end_chat` does nothing until then.
Whether the quoted text reached the target word for word is not measured yet; `Spans.sent`
keeps the data for those checks.

## Environment variables

The user agent and the runner agent are model roles. `model_settings.py` resolves them when a
trial is built, through `metis.core.model_settings`. The
[model guide](../../../../../../docs/guide/models.md) lists their variables, the fallback, and the
precedence of the Specification fields. Each `TrialConfig` records the models of its trial.

A target binding names the variables its runner reads (`spec_url`, `auth.secret_env`, `secret_headers`). Judge/evaluation variables (`JUDGE_API_KEY`, `JUDGE_BASE_URL`, `JUDGE_MODEL`) are documented in the [evaluation README](../evaluation/README.md).

## Running

Run from the project root. Use `uv run metis engine simulate` or activate the environment first.

```bash
metis engine simulate --input-dir path/to/my-experiment/
# Evaluate the output directory that simulate wrote. It prints this command.
metis engine evaluate --experiment-dir experiments/execute/my-experiment-20260820-143000/
```

Use `metis engine run --input-dir path/to/my-experiment/` for the combined simulation and evaluation flow.

Simulation uses the live TUI in a terminal. Evaluation uses a normal progress bar, reports linear per-record progress outside a terminal, and writes one complete `logs/evaluate.log` file.

## Structure

```
simulation/
├── factory.py         — RunnerFactory protocol
├── trial.py           — "Run one trial" seam; builds the trial and describes the fixtures
├── runner_resolver.py — Resolves runner_factory_ref FQN to a class
├── experiment.py      — Experiment orchestrator (worker distribution, asyncio.gather)
├── types.py           — Pydantic models (Specification, Scenario, Persona, Observation, Promise)
├── user_context.py    — Persona and scenario text, with their metadata, for the user agent
├── config.py          — Shared configuration (retry defaults)
├── exceptions.py      — Simulation-specific exceptions
├── _artifact_store.py — Artifact capture and storage
├── runner.py          — Runner ABC: setup, act, end_chat, teardown
├── orchestrator.py    — Turn loop; owns the ArtifactLedger
├── binding.py         — Loads a target binding from the experiment's inputs
├── evidence.py        — Pointers into the transport log
├── user_agent/        — Persona and scenario prompt, ⟦ ⟧ actions, file facts, promise list
└── runners/           — The generic runners
    ├── http.py            — HttpRunner and HttpRunnerFactory
    ├── browser.py         — BrowserRunner and BrowserRunnerFactory
    └── ...                — tools, rules, spans and prompts shared by both
```
