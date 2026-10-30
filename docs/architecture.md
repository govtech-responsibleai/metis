# METIS Product Suite — Architecture Specification

## Table of Contents

- [1. Purpose & Scope](#1-purpose--scope)
- [2. Notation](#2-notation)
- [3. Technology Constraints](#3-technology-constraints)
- [4. Workspace Structure](#4-workspace-structure)
- [5. Component Specification](#5-component-specification)
- [6. Dependency Invariants](#6-dependency-invariants)
- [7. Testing Contract](#7-testing-contract)
- [8. Build Interface Contract](#8-build-interface-contract)
- [9. Versioning](#9-versioning)
- [10. CLI Interface](#10-cli-interface)

---

## 1. Purpose & Scope

METIS (Measurement and Evaluation of Trustworthy Intelligent Systems) is an extensible agentic evaluation suite designed for whole-of-government adoption. It enables agency teams to build fast while ensuring AI safety, alignment, and operational reliability by default.

This document is the normative architectural specification for the METIS suite. It defines system boundaries, component contracts, dependency invariants, and the build interface. All implementation artifacts (code, configuration, CI pipelines) MUST conform to this specification.

---

## 2. Notation

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

---

## 3. Technology Constraints

| Concern | Requirement |
|---------|-------------|
| Workspace & Package Management | MUST use `uv` workspaces with a single root lockfile (`uv.lock`). |
| Data Modeling & Validation | MUST use Pydantic v2 for all shared domain objects. |
| Namespace Packaging | MUST use Hatchling with PEP 420 native namespace packages. |
| CLI Framework | MUST use Typer + Rich for all CLI surfaces. |
| Python Version | MUST target Python ≥ 3.11. |

---

## 4. Workspace Structure

The workspace is a Python monorepo. Directory names on disk are kept short (`packages/core`); code within each package uses the nested namespace layout (`src/metis/core`). All packages share a unified `metis` Python namespace.

```text
metis/
├── pyproject.toml              # Workspace root definition
├── metis_cli.py                # Unified CLI entry point (composes sub-package CLIs)
├── uv.lock                     # Single lockfile for the entire workspace
│
├── packages/                   # Reusable library packages
│   ├── core/
│   │   └── src/metis/core/
│   ├── library/
│   │   └── src/metis/library/
│   ├── engine/
│   │   └── src/metis/engine/
│   ├── wizard/
│   │   └── src/metis/wizard/
│   ├── insights/
│   │   └── src/metis/insights/
│   └── testbed/
│       ├── src/metis/testbed/
│       └── wizard/
│           ├── cases/         # Wizard reference cases and Specifications
│           └── reviewer/      # Local reference case reviewer
│
├── apps/                       # Deployable application services
│   ├── api/
│   │   └── src/metis/api/
│   └── web/                    # TypeScript/React frontend (separate toolchain)
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│
└── infra/                      # Docker Compose, Kubernetes, deployment assets
```

**Rules:**

- Each package MUST contain a `pyproject.toml` at its root and source code under `src/metis/<pkg>/`.
- The root project MUST explicitly list all workspace members as dependencies so that `uv sync` installs them into the virtualenv.
- There MUST be exactly one lockfile (`uv.lock`) at the workspace root.

---

## 5. Component Specification

### 5.1. `metis-core`

| | |
|---|---|
| **Import Path** | `from metis.core import ...` |
| **Purpose** | Domain schemas, abstract interfaces, registry, and shared infrastructure. Zero external runtime dependencies beyond Pydantic v2. |

MUST NOT depend on any other workspace member.

New shared file contracts MUST be defined in `metis-core`. All published `*.schema.json`
files MUST be generated from core models and stored in `packages/core/schemas/`.
Private runtime models and API request and response models stay in their owning packages.

---

### 5.2. `metis-library`

| | |
|---|---|
| **Import Path** | `from metis.library import ...` |
| **Purpose** | Shared catalog of graders, skills, and reusable components consumed by both the execution path (engine) and the configuration path (wizard). The wizard references items by FQN; the engine resolves and executes them. Lightweight layer so consumers can enumerate catalog items without pulling in engine's heavier dependencies. |

MUST depend only on `metis-core`. MAY depend on `openai` for the grader LLM client type.

---

### 5.3. `metis-engine`

| | |
|---|---|
| **Import Path** | `from metis.engine import ...` |
| **Purpose** | Evaluation runtime — ingests traces and executes graders. |

MUST depend on `metis-core` and `metis-library`. MAY depend on HTTP, math, parsing, browser automation, and LLM client libraries. MUST be usable both as a library import and as a standalone CLI. Every `Runner` implementation MUST satisfy the normative runner contract in [runner-contract.md](runner-contract.md).

---

### 5.4. `metis-wizard`

| | |
|---|---|
| **Import Path** | `from metis.wizard import ...` |
| **Purpose** | Interactive configuration generator for creating evaluation suites and guardrails. |

MUST depend on `metis-core` and `metis-library`. MUST NOT depend on `metis-engine`.

The wizard exposes a stateless Interview lifecycle interface (`handle_interview`,
`compile_specification`, `derive_stage`) and holds no server state: the Interview state is client-held and
travels whole on each operation. The wizard MUST NOT own an HTTP server or a frontend; a web client
reaches the Interview through `apps/api`. The CLI adapter drives the same lifecycle interface.

The wizard owns the final 12-item ARC capability catalogue in
`packages/wizard/src/metis/wizard/capabilities.yaml`. It serves the ordered categories through
`InterviewConfig.capability_categories` and uses the same data to validate the required
`InterviewStartRequest.known_capability_ids` and to build the general model background. The start
request also requires `capability_confidence` (`low`, `medium`, or `high`). A returned
`InterviewState` MUST contain `context.capability_evidence` with these values. Capability evidence
is client-held Interview context, outside `Specification`; it is not an Interview step and model
patches MUST NOT write it. An unselected capability is unknown, not evidence of absence.

---

### 5.5. `metis-insights`

| | |
|---|---|
| **Import Path** | `from metis.insights import ...` |
| **Purpose** | Analytics computation and reporting engine for evaluation outputs. |

MUST depend on `metis-core`. MUST NOT depend on `metis-engine` or `metis-library`.

---

### 5.6. `metis-testbed`

| | |
|---|---|
| **Import Path** | `from metis.testbed import ...` |
| **Purpose** | Component evaluations for Wizard, Engine, and Insights; evaluator calibration; and controlled comparisons with other systems. |

The current testbed contains the Wizard evaluation cases in
`packages/testbed/wizard/cases`. Each case separates product inputs, a reference
Specification in `outputs/`, and a README with source links and review notes.
The reference cases and local reviewer do not require an installed testbed
package. The evaluation runtime in PR #445 adds the installable
`metis-testbed` package; evaluation data remains in the repository.
All inputs are tracked.
See the [Wizard guide](../packages/testbed/wizard/README.md) for the review process.

A testbed runtime MAY depend on `metis-core`, `metis-engine`, `metis-wizard`, and
`metis-insights`. Product packages MUST NOT depend on the testbed. Component
adapters belong in the testbed so the same case data can support other systems.

---

### 5.8. `apps/api`

| | |
|---|---|
| **Import Path** | `from metis.api import ...` |
| **Purpose** | A thin, stateless HTTP door exposing METIS capabilities as a REST service. |

MAY depend on all `packages/*` members. For the wizard it depends on the `metis.wizard` public
Interview interface only (`apps/api -> metis.wizard`): the router calls `handle_interview`,
`compile_specification`, and the in-memory specification packager and maps typed results onto HTTP
responses. No stage, Specification, prompt, matching, fixture validation, or compilation rule lives in
the API. The package route accepts one JSON source part: `state` for an Interview or
`specification` for a manual export. A manual export can also send a `connection` part, which
gives the same run-mode export as an Interview with that connection. An Interview carries its
connection in its state. The route accepts request-scoped fixture bytes and returns one
dated ZIP archive; it retains no uploaded files. Wizard owns the archive filename
and dated root folder. The API sends the filename in `Content-Disposition`, and the
browser uses it for the download.

Wizard exports share `inputs/` and `outputs/` at the design root. The CLI defaults to
`experiments/design/YYYY-MM-DD-interview/`. An explicit `--out-dir` selects the exact root.
Resume requires that path. ZIP exports contain a dated `interview` or `manual` root
folder for extraction into `experiments/design/`. Interview exports MUST
compile from the same final state saved as `inputs/interview_state.json`. Manual exports MUST
include an empty `inputs/` folder. The Specification and fixtures belong under `outputs/`;
the existing CLI review belongs at `outputs/review.md`. Engine reads the `outputs/` folder.
The CLI publishes `outputs/specification.yaml` last as its completion marker and retains
recovery state until export succeeds. Wizard MUST NOT create Testbed caches or scores.

Engine creates `experiments/execute/<specification-id>-YYYYMMDD-HHMMSS/`. It copies
`--input-dir` into `inputs/`, writes trial records and artifacts under `outputs/trials/`,
and writes evaluation results to `outputs/reports/results.json`. Insights reads the
same execution root and writes `report.json` and `report.html` beside the results.
Insights reads recorded `GraderRecord` results and rejects the earlier `turn_results` and
`session_results` format. It uses recorded Criterion IDs and arguments without creating graders.
`--experiment-dir` identifies the execution root for evaluation and resume.
`metis.core.execution_layout` owns the paths shared by Engine and Insights.
Logs remain under `logs/`, with the existing simulation log override. Artifact paths
in trial records remain relative to the execution root.

`GET /api/v1/wizard/config` returns the wizard-owned ordered ARC capability categories with the
opening copy and perspective definitions. `POST /api/v1/wizard/interview/start` accepts the
description, required known capability ids, required confidence, and any other opening choices,
then passes them to the wizard facade. The API does not validate or store a separate capability
catalogue.

**Client-held state boundary.** The service holds only immutable settings and model clients for the
process lifetime. It holds no Interview state: start creates state, turn carries the complete state
and one typed response, and end carries the complete state for best-effort completion. The next state
goes back whole in the response, so any instance serves any operation and no Interview file is
written. Web clients drive the wizard through these HTTP lifecycle routes; they MUST NOT embed the
wizard.

---

### 5.9. `apps/web`

| | |
|---|---|
| **Purpose** | Web frontend providing a graphical interface for METIS capabilities. |

MUST communicate exclusively with `apps/api` via REST. MUST NOT import or depend on any Python package directly.
The browser owns the local Interview record, fixture Blobs, and display transcript in IndexedDB. It
sends only the client-held `InterviewState` and typed responses to lifecycle routes; fixture bytes
are sent only for request-scoped text extraction or packaging. It MUST NOT depend on server Interview
resources, wizard static assets, or an embedded wizard runtime.

It MUST offer two authoring paths: the guided Interview, and a manual form for a user who already
knows the graders to run. The manual form MUST stay flat: it MUST NOT surface Feature, Behaviour, or
Criterion. It MUST build a valid `Specification` in the browser and submit it to the existing
package route, and it MUST NOT add a route or create an Interview record. Server-side validation in
`metis-wizard` stays authoritative for both paths.

In this first version the manual form collects only what an engine run absolutely needs. The engine
reads the complete `specification.yaml`. Reporting reads its frozen copy at
`inputs/specification.yaml`. `metis.core.profile.TargetProfile` holds Target context
and the Feature → Behaviour → Criterion hierarchy. `metis.core.experiment.Experiment`
holds Personas, Scenarios, Tasks, and execution settings. Its optional `target_binding`
names a `metis.core.target_binding.TargetBinding` file, relative to `specification.yaml`,
which the generic runner reads. In run mode, the Wizard exports `target-binding.yaml` next to
`specification.yaml` and sets `runner_factory_ref` to the generic HTTP or browser factory as an
FQN string. The Wizard MUST NOT import the engine to do this. The binding names environment
variables only. It travels in the client-held Interview context, and prompts MUST NOT read it.
`metis.core.specification.Specification` contains a Profile and the configuration needed to conduct an Experiment.
The serialized document keeps these fields at the top level.
Each Task selects one Scenario, one Persona, fixtures, a Trial count, and measured Behaviours.
Every selected Behaviour supplies all its Criteria to grading.
Each Criterion owns its Grader FQN and parameters. Scores retain Task, Trial,
and Criterion identity plus the Grader configuration.

Each Criterion states one assessable requirement. Review shows its description with
expandable Grader settings. Wizard edits MUST keep the description and settings
consistent. Direct edits validate fields and arguments. Users maintain their agreement.
The criterion judge uses the complete description as its assessment instructions.

Engine MUST build one grader per active Criterion from the specification snapshot
and reuse it across sessions. Results MUST preserve their order, Criterion IDs,
configured grader paths, and validated arguments, including resolved defaults.
Insights reads these recorded values without creating graders.

The normal local run uses two processes: `PORT=8001 uv run metis-api` and
`npm --prefix apps/web run dev`. `make run-web` starts both through `scripts/run-dev.sh`, which labels
each line of output and stops every server when one of them ends. The two processes stay
independent: the script starts them and adds no layer between them, and `make run-api` starts
the API alone.
The Vite proxy uses `METIS_API_ORIGIN`, defaulting to `http://127.0.0.1:8001`.
The opening web screen renders the complete ordered capability catalogue and sends the selected
ids and confidence with the target description in one start request.

---

## 6. Dependency Invariants

Dependencies MUST flow downward only. The following DAG is normative:

```text
[ apps/web ] ──HTTP──▶ [ apps/api ] ───────────────────────┐
                            │                               │
                            ▼                               ▼
                       [ packages/engine ] ◄── [ packages/testbed ]   [ packages/wizard ]
                            │         │                               │
                            │         ▼                               │
                            │   [ packages/insights ]                 │
                            │                                         │
                            ▼                                         ▼
                     [ packages/library ] ◄───────────────────────────┘
                            │
                            ▼
                     [ packages/core ]   (Base — zero local dependencies)
```

> `apps/web` has no compile-time dependency on any Python package. Its only runtime dependency is the HTTP API surface exposed by `apps/api`.

**Invariant Rules:**

1. `metis-core` MUST NOT depend on any other workspace member.

2. `metis-library` MUST depend only on `metis-core`.
3. `metis-wizard` MUST NOT depend on `metis-engine` or `metis-insights`.
4. `metis-insights` MUST NOT depend on `metis-engine`, `metis-library`, or `metis-wizard`.
5. `metis-engine` MUST NOT depend on `metis-wizard` or `metis-insights`.
6. No circular dependencies SHALL exist between any workspace members.
7. Upward dependencies (child depending on parent in the DAG) MUST NOT be introduced.
8. `apps/web` MUST NOT import or depend on any Python workspace member at compile time.

---

## 7. Testing Contract

### Directory Layout

```text
tests/
├── unit/                       # Per-package isolation tests
│   ├── core/
│   ├── library/
│   ├── engine/
│   ├── wizard/
│   └── insights/
├── integration/                # Cross-package flow tests
└── fixtures/                   # Shared test data
    ├── langfuse_trace.json
    └── specification.yaml
```

The web client workflow and its deferred features are documented in the
[Wizard web guide](guide/wizard/web.md).

### Rules

- Unit tests (`tests/unit/<package>/`) MUST test a single package in isolation. External dependencies SHOULD be mocked.
- Integration tests (`tests/integration/`) MUST verify cross-package flows.
- Test fixtures (`tests/fixtures/`) MUST hold shared sample data. Tests MUST NOT embed fixture data inline when a shared fixture exists.
- The full test suite MUST be runnable via `uv run pytest` from the workspace root.
- Per-package test runs MUST be supported: `uv run pytest tests/unit/<package>/`.

---

## 8. Build Interface Contract

A root `Makefile` MUST provide the following targets as the public development and CI interface:

| Target | Behavior |
|--------|----------|
| `install` | Install all workspace dependencies (including dev group). |
| `lint` | Run Ruff lint checks. MUST fail on violations. |
| `lint-fix` | Apply Ruff lint autofixes. |
| `format` | Format all Python files with Ruff. |
| `format-check` | Check formatting without modifying files. MUST fail on violations. |
| `fix` | Apply lint autofixes and format (convenience composition). |
| `typecheck` | Run Pyright type checking. MUST fail on errors. |
| `test` | Run the full test suite via pytest. |
| `test-unit` | Run unit tests only. |
| `test-integration` | Run integration tests only. |
| `check` | Composition: `lint` + `format-check` + `typecheck`. |
| `check-web` | Run non-mutating `apps/web` formatter, type checker, tests, and API drift checks. |
| `build-web` | Run the production `apps/web` build. This target writes the normal Vite output. |
| `ci` | Composition: `check` + `check-web` + `build-web` + `test` + core schema checks. MUST mirror what CI pipelines execute. |
| `clean` | Remove all generated/cached files across the monorepo. |

**Rules:**

- All targets MUST operate from the workspace root.
- The `ci` target MUST be the single command that reproduces a CI pipeline run locally.
- `check` and `check-web` MUST be non-mutating (read-only verification).

---

## 9. Versioning

The workspace uses **independent semantic versioning** — each package maintains its own version, and releases are tracked with scoped git tags.

### 9.1. Design Rationale

Independent versioning is chosen over a unified "METIS version" for the following reasons:

- Each package is owned by a separate engineer. Per-package versions serve as a coordination and project management signal per team.
- Lightweight consumers can pin and track just the packages they depend on.

**Tradeoffs:**

- There is no single unified "METIS version" — the product identity is a tuple of package versions.
- Git tags form a flat interleaved stream across packages.
- A **compatibility manifest** (`COMPATIBILITY.md` at the workspace root) SHOULD be maintained to record which package versions have been validated together as a working set.

### 9.2. Mechanism

Each package declares a static `version` field in its `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]

[project]
name = "metis-engine"
version = "0.2.0"
```

The `pyproject.toml` is the single source of truth for each package's version.

### 9.3. Rules

- All packages MUST declare a static `version` field in `pyproject.toml`. No package MAY use dynamic version derivation.
- All versions MUST be SemVer-compliant (`MAJOR.MINOR.PATCH`).

### 9.4. Git Tag Convention

Released versions are marked with scoped annotated git tags:

- **Format:** `<package-name>/v<semver>` (e.g., `metis-engine/v0.2.0`, `metis-core/v0.1.0`)
- **Creation:** `git tag -a metis-engine/v0.2.0 -m "metis-engine v0.2.0"`
- **Per-package listing:** `git tag -l "metis-engine/*"`

Tags are markers, not sources of truth. The `version` field in `pyproject.toml` is authoritative.

### 9.5. Tag-on-Merge Rule

Every merge to `main` that modifies source code under `packages/` or `apps/` MUST be tagged with a scoped version bump for the affected package(s).

- Multi-package PRs MUST receive one tag per affected package.
- **Exemption:** Merges that only touch root-level files (docs, CI config, `Makefile`, `.github/`, `infra/`) do NOT require a tag.

### 9.6. Release Workflow

1. Bump `version` in the affected package's `pyproject.toml`.
2. Commit the version bump as part of the PR (or as the merge commit).
3. Tag the merge commit: `git tag -a <package-name>/v<version> -m "<package-name> v<version>"`.
4. Push with `--tags`.

### 9.7. Commit Message Convention

All commits on `main` MUST be prefixed with the affected scope:

```text
engine: fix trace parsing for nested spans
core: add Span.duration computed field
wizard: update prompt templates for v2 schema
docs: update architecture spec versioning section
ci: add tag enforcement check
infra: update Docker base image
```

Package scopes (`core`, `library`, `engine`, `wizard`, `insights`, `api`, `web`) correspond to versioned artifacts and require a tag. Cross-cutting scopes (`docs`, `ci`, `infra`) do not.

### 9.8. CLI Version Reporting

The unified `metis --version` SHOULD print a breakdown of all installed component versions:

```text
metis 0.1.0
  core    0.1.0
  library 0.1.0
  engine  0.2.0
  wizard  0.1.0
```

### 9.9. Schema Versioning

Schema versions (for data formats like `specification.yaml` and `session-record.json`) are independent integers maintained in source code constants, not tied to package versions.

---

## 10. CLI Interface

The primary user-facing CLI is the unified `metis` command, which composes sub-package CLIs under `metis <package> <subcommand>`.

Per-package standalone commands (e.g., `metis-engine`, `metis-wizard`) MUST also be available for CI or isolated installs.

`metis wizard init` collects the description, a capability selection (including an explicit blank
selection), and one required confidence value before it sends `InterviewStartRequest`. It asks
for the description with the package opening question. This input does not add a step or
confirmation lock.
