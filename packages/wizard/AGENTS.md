# metis-wizard

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

IMPORTANT: Always talk in ASD-STE100 Simplified Technical English.

## Package Purpose

Interactive wizard that turns a prose description of a target into a runnable `specification.yaml`.
Depends on metis-core and metis-library.

The design record lives in these files:
- Root `GLOSSARY.md` — the vocabulary authority. Use its terms in code, tests, prompts, and UI.
- `docs/architecture.md` — the normative architecture specification.
- `openspec/changes/` — the active and archived proposals, designs, and delta specs. This is the
  living design record for each wizard change.

The user guide starts at `docs/guide/wizard.md`. Interface-specific instructions live in
`docs/guide/wizard/cli.md`, `docs/guide/wizard/web.md`, and `docs/guide/wizard/api.md`.

## Working style

**Build the service before the frontend.** The interview lives in the application/contracts/domain
layers, and the web UI is a demo over it. When a change touches both, land the service behaviour —
models, driver, interview, door contract — first and get it right, then wire the frontend to it. Do
not shape the service around what is convenient for the current UI.

**Use the root glossary as the vocabulary authority.** Before naming or changing a concept, read
the glossary at the repository root and use its terms consistently in code, documentation,
prompts, tests, and UI. Reuse existing glossary terms and do not invent new terminology. If the
needed concept is not in the glossary, propose a glossary update before introducing a new term.

**Never use a term you have not shown the user.** Jargon, internal names, and concepts from the
design must be introduced before they are used — with a concrete example, not a definition in
passing. If a term appears for the first time in an explanation or a question, stop and explain it
there. This applies to standard technical terms as well as project vocabulary.

**Design data models with OOP where possible.** Prefer a shared base class over repeating the same
fields across several models. Prefer inheritance and composition over flags and optional fields
that are only meaningful in some cases — if a class has fields that sit empty most of the time,
that is a signal it should be several classes.

```python
# a base holds what every request shares
class WizardRequest(BaseModel):
    prompt: str


# each kind adds only what it actually needs
class ChatRequest(WizardRequest):
    type: Literal["chat"] = "chat"


class FormRequest(WizardRequest):
    type: Literal["form"] = "form"
    fields: list[FormField]
```

**Name a model after what it belongs to.** A nested model or enum carries its owner's name, so the
link is visible without having to look anything up:

```python
Patch.op            → PatchOp
Card.lines          → CardLine
FormRequest.fields  → FormField
```

The exception is a genuinely shared type used by several owners — `Option` appears on
`ChoiceRequest`, on `Card` and on `Warning`, so tying it to any one of them would be misleading.

**Leave light comments in the code.** Enough to follow what something does and why it exists,
especially where the reasoning is not obvious from the code itself. Comment the decision, not the
syntax.

```python
# criteria are kept when a behaviour is unticked — they go dormant rather than being
# deleted, and Tasks can select only `measured` behaviours. this is what
# lets the tick stay live without needing any staleness tracking.
behaviour.measured = False
```

## Module layout

The package is split by ownership so a door lives at the edge and the interview does not move with
it. The interview is driven through a stateless lifecycle interface (`handle_interview`,
`compile_specification`, `derive_stage`); the state is client-held and travels whole on each operation.
The CLI is the only door inside the package. A web client reaches the same interface over HTTP
through `apps/api`; the wizard owns no HTTP server and no frontend.

```
src/metis/wizard/
├── domain/       specification, patches, path resolution, permissions and edit impacts
├── contracts/    requests, responses, cards, warnings, model outputs, the Interview transaction, and
│                 the client-held InterviewState
├── application/  handle_interview, driver, stage derivation, readiness, prompts, screens, compiler,
│                 matcher and primer
├── adapters/
│   ├── cli/      Typer commands, Rich renderer and terminal input
│   └── llm/      LLM gateway: structured output
├── bootstrap.py  the only adapter composition root
└── __init__.py   stable headless facade: the Interview interface and interaction models
```

Dependencies point inward: adapters depend on application/contracts/domain, application depends
on contracts/domain, and contracts depend on domain. Adapter siblings never import one another;
`bootstrap.py` is the sole exception because it composes the production CLI.

## POC testing policy

Keep tests small and focused while the wizard is a POC with no dependants. Cover the main user
workflow and failures that would lose user data, bypass user review, or exceed processing limits.
Use representative cases; exhaustive edge-case matrices are not a release requirement. Add a test
only when it protects an outcome not already covered. Test count and coverage percentage are not
goals. Reassess this policy when the wizard has released users or dependants.

## Testing

`make test` runs the root `tests/` tree. The wizard's unit tests live under `tests/unit/wizard/`
grouped by ownership, its integration tests under `tests/integration/wizard/`, and its shared
fixtures under `tests/fixtures/wizard/`.

Keep the suite organised around the wizard's stable contracts, not around the sequence of fixes
that produced them:

- Give each behaviour cluster one authoritative application/domain test module. Extend an existing
  parametrized workflow matrix before creating another narrowly named test.
- When behaviour changes, update the existing contract tests and remove obsolete coverage.
- Test shared interview behaviour at the driver/interview layer. Door tests should prove that the CLI
  and HTTP adapters preserve that behaviour, using representative or parametrized cases instead of
  repeating every driver example.
- Keep frontend tests light while the wizard web UI is a demo: cover critical interaction wiring
  and shared-door contracts, not every visual detail or microinteraction.
- Exact copy deserves a direct assertion only when the wording is a normative part of the user
  contract. Constants deserve direct tests only when their identity or location is an architectural
  constraint; otherwise test their observable behaviour.
- Multiple OpenSpec scenarios can be covered by one table-driven test. Implementation tasks do not
  each require their own test.

Keep prompt tests lean so wording can change quickly:

- Keep prompt composition coverage in `tests/unit/wizard/application/test_prompts.py`. Check
  catalogue loading, template substitution, and required context with unique test values.
- Avoid full-prompt snapshots and assertions on instruction sentences, examples, or prose order.
  Wording-only edits should not require test edits. Change tests when the contract changes.
- Test patch permissions, reference validation, and state changes at their owning layers. Do not
  repeat prompt text assertions in gateway, driver, API, or browser tests.
- Check model response quality with representative output review or focused evaluations. A test
  that finds an instruction in a prompt does not prove that the model follows it.

Two integration tests are gates rather than unit tests:

- **`tests/integration/wizard/test_slice_a_gate.py`** — a hand-written specification compiles to a `specification.yaml` the
  engine actually loads, via the engine's own `_validate_inputs`. No model call anywhere in it.
- **`tests/integration/wizard/test_slice_b_gate.py`** — the whole interview walks to DONE on `ScriptedInterviewer`,
  with no network. That stand-in in `tests/fixtures/wizard/scripted.py` is **not a throwaway**: it is
  the offline regression suite for Interview flow and matching. It does not test whether a live model
  follows the prompts. Keep it working.

`tests/fixtures/wizard/golden_specification.yaml` is a golden file. Regenerate with
`uv run python tests/fixtures/wizard/regenerate_golden.py` — and read the diff before
committing it, or it stops buying anything.

`tests/integration/wizard/test_cli_happy_path.py` drives the actual Typer app through `CliRunner` with
the scripted interviewer. It is the offline full happy-path check for `specification.yaml`.

## Langfuse tracing

The model gateway records prompts, raw replies, retries, token counts and latency in a
self-hosted Langfuse server. The target server release is `v3.153.0`, with the Python SDK v3
line.

The gateway imports its client from `langfuse.openai`. This is a drop-in for the OpenAI client:
the import makes every model call record a trace, with no tracing code in the retry loop. The
gateway wraps `_ask` with `@observe`, so the three attempts of one call are in one trace. The
trace has the name of the Interview step. A caller can also give the gateway an Interview ID to
group its traces. The stateless lifecycle does not carry an Interview ID, so the CLI and API
normally record these traces ungrouped; the missing ID does not prevent tracing.

`langfuse` is a base dependency, so it installs with the wizard. The traces go to the
METIS-internal Langfuse. To turn tracing on, set these three environment variables before you
start the wizard:

- `METIS_INTERNAL_LANGFUSE_BASE_URL`
- `METIS_INTERNAL_LANGFUSE_PUBLIC_KEY`
- `METIS_INTERNAL_LANGFUSE_SECRET_KEY`

Tracing is off when a variable is missing. There is no default host, so no interview content goes
anywhere until an operator gives their own instance. The wizard never falls back to the
`LANGFUSE_*` variables. Those name the Langfuse of the system under test, which the engine reads,
and a fallback would put Interview content in the target's project.

The gateway gives the Langfuse client its keys directly, and every traced call names that client
by its public key. A client built without keys reads `LANGFUSE_*`, so when tracing is off the
gateway registers a disabled client under a placeholder key. When tracing is off, the client
sends nothing. It writes traces on a background thread, so tracing does not block or
stop the interview. There is no wizard-owned failure-safe wrapper: the wizard uses the behaviour
of the library.

## Things that look like bugs and are not

- **Ticks toggle.** Each option's patch flips that behaviour's *current* value, so sending the
  same tick twice turns it off. Correct, and a trap when scripting a walk.
- **Ids must not contain a dot.** A dot separates path segments, so `AC-1.1` would split
  `criteria[AC-1.1]` into two segments. Criterion ids are `AC-<behaviour>-<n>` for that
  reason. `paths.parse` scans segment-by-segment rather than splitting, so a model that
  ignores the rule still produces an addressable path — but the naming rule is the fix, and
  it is stated in the system prompt.
- **Paths resolve by real id only.** Paths address by id (`behaviours[EB-1]`); a numeric bracket
  such as `behaviours[0]` is rejected rather than treated as a positional fallback. This keeps
  references attached to the same items when lists are reordered.
- **`ADD` addresses the container** (`features`, `scenarios`), `SET`/`REMOVE` an element
  (`features[F-1]`). `StepPermissions` must list both or half the operations are silently
  forbidden.
- **Strict drafts own the boundary.** Provider JSON is parsed into strict, model-only draft
  models (`extra="forbid"`) before any persisted specification object exists. The application
  materializer then assigns ids, authorship, defaults and references. The old recursive value
  filter was only a compatibility guard for hand-built runtime patches; it never protected the
  real typed provider path.

## Package-Specific Notes

The wizard calls one model role: the interview. Grader matching is one more structured call on
that role. `adapters/llm/gateway.py` resolves it through `metis.core.model_settings`
(`INTERVIEW_*`, then `OPENAI_*`). `OPENAI_BASE_URL` is optional. `configure_interview_runtime`
takes the resolved settings and never writes them to `os.environ`. `init` and `resume` read the
one `.env` that core finds and check the role before the first model call. After the files are written, the CLI lists the roles that the run
needs, with model and status. See [the model guide](../../docs/guide/models.md).

The grader catalogue now reads from **metis-library** (`metis.library.graders.*`), so
`application/matching/library_catalogue.py` is back on the DAG. It enumerates the classes
re-exported flat from `metis.library.graders.__init__` and emits canonical FQNs
`metis.library.graders.<Class>`; the `GraderSpec`/`GraderParam` types it returns live in
`contracts/grader_spec.py`.

The compiler validates the shared Specification in `metis.core.specification` and writes one
`specification.yaml`. It does not depend on the engine. Tasks own execution references,
fixtures, and Trial counts. Criteria own Grader FQNs and parameters. Preserve Task IDs
through edits; assign a new ID for a copy. The backend returns assigned IDs to clients.
