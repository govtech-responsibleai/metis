# METIS — Codebase Guide

## Overview

METIS (Measurement and Evaluation of Trustworthy Intelligent Systems) is a Python monorepo providing an extensible agentic evaluation suite. It ingests agent execution traces and runs configurable metrics to produce safety/alignment diagnostics.

## Tech Stack

- **Language:** Python ≥ 3.11
- **Workspace/Package Manager:** uv (single lockfile at root)
- **Build Backend:** Hatchling (static version in each package's `pyproject.toml`)
- **Data Modeling:** Pydantic v2
- **CLI Framework:** Typer + Rich
- **Linting/Formatting:** Ruff
- **Type Checking:** Pyright
- **Testing:** pytest
- **Dev Environment:** direnv (`.envrc` auto-activates venv)

## Commands

```bash
make install        # uv sync and npm install for all workspace tools
make check          # lint + format-check + typecheck (non-mutating)
make fix            # auto-fix lint + format
make ci             # full CI suite (check + test)
make clean          # remove generated/cached files
```

The browser client is a separate Node project. Run `make install-web` once, then use
`make check-web` for non-mutating formatting, type checking, tests, and API-contract drift checks.
Use `make build-web` for the production build. For local development, `make run-web` starts the
API and the web dev server, with a label on each line of output. Ctrl-C stops them, and a server that
stops on its own takes the other one with it. To start the API server only, run `make run-api`.
Set `METIS_API_ORIGIN` when the API is not on port 8001.

Individual targets: `lint`, `lint-fix`, `format`, `format-check`, `typecheck`.

Test targets: `test`, `test-unit`. Integration tests are scaffolded but not yet active.

## Project Layout

```
metis/
├── pyproject.toml          # Workspace root (lists all members)
├── metis_cli.py            # Unified CLI entry point (composes sub-CLIs)
├── uv.lock                 # Single lockfile
├── Makefile                # Dev/CI interface
├── packages/
│   ├── core/               # metis-core — domain schemas, interfaces, registry
│   ├── library/            # metis-library — shared catalog (metrics, skills, etc.)
│   ├── engine/             # metis-engine — evaluation runtime + trace ingesters
│   ├── wizard/             # metis-wizard — interactive config generator
│   └── insights/           # metis-insights — report generation from evaluation results
├── apps/
│   ├── api/                # REST backend
│   └── web/                # React frontend
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
    └── architecture.md     # Normative architectural specification
```

Each package lives under `packages/<name>/src/metis/<name>/` using PEP 420 namespace packages.

## Dependency DAG (downward only)

```
engine ──► library ──► core
wizard ──► library ──► core
insights ───────────────► core
```

Key invariants:
- `core` has zero workspace dependencies (Pydantic + structlog + Rich + python-dotenv + stdlib)
- `library` depends only on `core`
- `wizard` and `engine` depend on `core` + `library` but NOT on each other
- `insights` depends only on `core`

## Shared schema ownership

New shared file contracts MUST be defined in `metis-core`. All published `*.schema.json`
files MUST be generated from core models and stored in `packages/core/schemas/`.
Private runtime models and API request and response models stay in their owning packages.

Register each published schema in `packages/core/scripts/generate_schema.py`. Run
`make -C packages/core generate-schema` and `make -C packages/core check-schema`.
See [the schema guide](packages/core/schemas/README.md).

## Architecture

- **metis-core:** Domain schemas (Trace, Span, Score, etc.), abstract interfaces (BaseTraceIngester), plugin discovery via entry points.
- **metis-library:** Shared catalog of graders, skills, and reusable components; referenced by FQN from wizard configs and executed by the engine.
- **metis-engine:** Evaluation runtime — simulation harness, trace extraction (Langfuse), and grader execution. CLI: `metis engine simulate --input-dir <path>`.
- **metis-wizard:** Interactive CLI for generating evaluation config YAML. CLI: `metis wizard init`.
- **metis-insights:** Report generation from evaluation results — the terminal summary, `report.json`, and `report.html`. CLI: `metis insights report --results-file <path>`.
- **apps/web:** React browser client. It calls `apps/api` over HTTP and stores Interview records and
  the display transcript in browser-local IndexedDB. It does not import Python packages or use the
  wizard's retired server/static-web path. It gives the user two ways to author an experiment: the
  guided Interview, and a manual form for a user who already knows the graders to run. The manual
  form is flat — it never shows Feature, Behaviour, or Criterion — and it builds its own
  `Specification` in the browser, which it sends to the existing package route.

## Contributing

All contributors (human and AI) MUST follow the guidelines in [CONTRIBUTING.md](CONTRIBUTING.md). This includes branching conventions, commit message style, testing requirements, dependency DAG invariants, and PR expectations.

## Documentation for work in progress

Treat user corrections as part of the final design. Write documentation, comments,
and tests as if that design was present from the start of the current work. Omit
temporary fields, abandoned approaches, and the sequence of feedback.

## Coding Conventions

- Namespace imports: `from metis.core import ...`, `from metis.engine import ...`
- Operational logging: `from metis.core.logging import get_logger` — structured events to stderr (debug, diagnostics, audit)
- User-facing output: `from metis.core.console import console` — Rich-formatted output to stdout (tables, progress, results)
- Never use `print()` or `logging.getLogger()` directly — use the core module APIs above
- Imports used only in type annotations belong in `if TYPE_CHECKING:` blocks (enforced by ruff `TCH` rule). Exception: Pydantic field types must remain runtime imports because Pydantic resolves annotation strings at runtime via `get_type_hints()`.
- All shared domain objects use Pydantic v2 models
- CLIs use Typer with sub-app composition (see `metis_cli.py`)
- Versioning: independent per package via static `version` in `pyproject.toml`; scoped git tags `<package-name>/v<semver>`
- Release workflow: develop on `release/<package>/v<semver>` branch → merge to `main` → tag the merge commit (`<package>/v<semver>`)
- Every merge to `main` MUST be tagged with a version bump for the affected package(s)
- Beta exception: while v1 is in beta, all packages share one version (`1.0.0bN`) and each beta gets
  one suite tag `v1.0.0bN`; see "Beta releases" in [CONTRIBUTING.md](CONTRIBUTING.md)
- Commit messages MUST use a Conventional Commit type and the package scope in parentheses:
  `feat(wizard): split prompt configuration ownership`. Use the affected package name as the
  scope (`core`, `library`, `engine`, `wizard`, or `insights`), not the `metis-` distribution
  prefix. Common types are `feat`, `fix`, `refactor`, `test`, `docs`, and `chore`.

## Per-Package Guides

When working on a specific package, read its local `AGENTS.md` for package-specific instructions:

- [`packages/core/AGENTS.md`](packages/core/AGENTS.md) — metis-core
- [`packages/library/AGENTS.md`](packages/library/AGENTS.md) — metis-library
- [`packages/engine/AGENTS.md`](packages/engine/AGENTS.md) — metis-engine
- [`packages/wizard/AGENTS.md`](packages/wizard/AGENTS.md) — metis-wizard
- [`packages/insights/AGENTS.md`](packages/insights/AGENTS.md) — metis-insights
- [`apps/api/AGENTS.md`](apps/api/AGENTS.md) — metis-api
- [`apps/web/AGENTS.md`](apps/web/AGENTS.md) — metis-web

See `docs/architecture.md` for the full normative specification.
