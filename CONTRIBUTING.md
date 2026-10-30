# Contributing to METIS

Thank you for contributing to METIS. This guide covers expectations and best practices for the monorepo — whether you're on the core team or contributing externally.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Monorepo Orientation](#monorepo-orientation)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Adding New Packages or Extensions](#adding-new-packages-or-extensions)
- [Pull Requests](#pull-requests)
- [Dependency Rules](#dependency-rules)
- [Versioning & Release](#versioning--release)
- [Support and contributions during the beta](#support-and-contributions-during-the-beta)
- [Getting Help](#getting-help)

## Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (workspace and package manager)
- [direnv](https://direnv.net/) (optional — auto-activates the virtualenv)

## Getting Started

```bash
git clone <repo-url>
cd metis
make install    # installs all workspace packages + dev tools
make check      # verify everything passes (lint + format + typecheck)
```

If you use direnv, the `.envrc` will activate the virtualenv automatically. Otherwise, prefix commands with `uv run` or activate `.venv` manually.

## Monorepo Orientation

```
metis/
├── packages/           # Reusable library packages
│   ├── core/           # Domain schemas, interfaces, registry
│   ├── library/        # Shared catalog (metrics, skills, etc.)
│   ├── engine/         # Evaluation runtime + trace ingesters
│   └── wizard/         # Interactive config generator
├── apps/               # Deployable services (Stage 3+)
├── docs/               # Architecture spec, design docs
├── metis_cli.py        # Unified CLI entry point
└── pyproject.toml      # Workspace root
```

Dependencies flow **downward only**:

```
engine ──► library ──► core
wizard ──► library ──► core
insights ───────────────► core
```

For the full specification (component contracts, dependency invariants, versioning), see [docs/architecture.md](docs/architecture.md).

## Development Workflow

### Branching

Branch off `main` with a descriptive prefix:

| Prefix | Use |
|--------|-----|
| `feat/` | New functionality |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `refactor/` | Code restructuring (no behavior change) |
| `test/` | Adding or improving tests |

Example: `feat/langfuse-ingester`, `fix/score-validation`

While v1 is in beta, `next` replaces `main` in the rule above. Branch off `next` and open your
pull request against `next`. `main` only changes at release time (see "Beta releases"), so it
always matches the latest beta tag.

### Running Checks

```bash
make check          # lint + format-check + typecheck (non-mutating)
make fix            # auto-fix lint + format
make ci             # full CI suite (check + test)
```

Run `make check` before pushing. CI will reject PRs that fail.

When you change a wizard HTTP request or response, update the Pydantic contract in
`packages/wizard` first. Then regenerate the committed web types with
`npm --prefix apps/web run generate:api` and run `npm --prefix apps/web run check:api`. Do not edit
`apps/web/src/generated/api.ts` by hand.

### Commit Messages

We follow a convention for commit messages [borrowed from Deis/CoreOS/AngularJS](https://github.com/deis/deis/blob/master/CONTRIBUTING.md#commit-style-guideline). The format is:

```
{type}({scope}): {subject}

{body}

{footer}
```

**Rules:**

- `{type}` is one of: `feat`, `fix`, `docs`, `style`, `ref`, `test`, `chore`
- `{scope}` is the affected package or app name (e.g., `core`, `engine`, `wizard`, `api`)
- `{subject}` uses imperative present tense ("change", not "changed"), no capital first letter, no trailing dot
- Subject line limited to **50 characters**; body lines limited to **72 characters**
- `{body}` explains the motivation and contrasts with previous behavior
- `{footer}` mentions any breaking changes with migration notes

**Examples:**

```
feat(engine): add Langfuse trace ingester for production observability

fix(core): handle missing timestamps in score aggregation

chore(wizard): initialize release v0.4.0
```

Avoid generic messages like "fix bug" or "update code".

## Code Standards

| Concern | Tool | Notes |
|---------|------|-------|
| Linting | Ruff | All rules enforced in `pyproject.toml` |
| Formatting | Ruff | Single style, no debate |
| Type checking | Pyright | Strict mode; all public APIs must be typed |
| Data models | Pydantic v2 | All shared domain objects |
| CLIs | Typer + Rich | Sub-app composition pattern |

### Conventions

- **Namespace imports:** `from metis.core import ...`, `from metis.engine import ...`
- **Static version fields:** Each package declares `version = "X.Y.Z"` in its `pyproject.toml` (no dynamic derivation)
- **Package source layout:** `packages/<name>/src/metis/<name>/`

### Shared file schemas

New shared file contracts MUST be defined in `metis-core`. All published `*.schema.json`
files MUST be generated from core models and stored in `packages/core/schemas/`.
Private runtime models and API request and response models stay in their owning packages.

Register each new published schema in `packages/core/scripts/generate_schema.py`.
Run `make -C packages/core generate-schema` and commit the generated file.
`make ci` checks schema ownership, registration, and generated content. See the
[schema guide](packages/core/schemas/README.md) for version and validation rules.

## Testing

```bash
make ci                 # run everything
uv run pytest           # full suite
uv run pytest tests/unit/core/   # single package
```

### Where Tests Go

| Type | Location | Scope |
|------|----------|-------|
| Unit | `tests/unit/<package>/` | Single package in isolation |
| Integration | `tests/integration/` | Cross-package flows |
| Fixtures | `tests/fixtures/` | Shared sample data (traces, configs) |

### Guidelines

- Unit tests should mock external dependencies, not sibling packages.
- Use shared fixtures from `tests/fixtures/` — don't inline large test data.
- New functionality should include tests. Bug fixes should include a regression test.

## Adding New Packages or Extensions

METIS is designed for extensibility at two main points:

- **Custom graders** — implement a grader class in `metis.library.graders` (see `packages/library/AGENTS.md`)
- **Custom trace ingesters** — implement `BaseTraceIngester` and register via the `metis.trace_ingesters` entry point group

For details on contracts and constraints, see the [Architecture Specification](docs/architecture.md).

When adding a new workspace package:

1. Create the directory under `packages/<name>/src/metis/<name>/`
2. Add a `pyproject.toml` following the existing pattern (hatchling with static `version`)
3. Respect the dependency DAG — no upward or circular dependencies
4. Register it in the root `pyproject.toml` workspace members

## Pull Requests

### Before Opening

- [ ] `make check` passes locally
- [ ] New code has tests
- [ ] No unrelated changes bundled in

### What Reviewers Look For

- Adherence to the dependency DAG (no upward imports)
- Type annotations on public APIs
- Focused scope — one concern per PR

### Merging

PRs require at least one approval. CI must pass. Squash-merge is preferred for single-concern branches; merge commits are acceptable for larger feature branches with meaningful intermediate commits. While v1 is in beta, the release merge of `next` into `main` is
always a merge commit, never a squash (see "Beta releases").

## Dependency Rules

These invariants are **non-negotiable** — CI will enforce them:

1. `metis-core` has zero workspace dependencies
2. `metis-library` depends only on `metis-core`
3. `metis-engine` and `metis-wizard` depend on `core` + `library` but NOT on each other
4. `metis-insights` depends only on `metis-core`
5. No circular dependencies, ever

When in doubt, check the DAG in [docs/architecture.md](docs/architecture.md).

## Versioning & Release

Each package is versioned independently via a static `version` field in its `pyproject.toml`.

The naming conventions are:
- **Branch:** `release/<package-name>/v<semver>` (e.g., `release/metis-engine/v0.2.0`)
- **Tag:** `<package-name>/v<semver>` (e.g., `metis-engine/v0.2.0`)

The `release/` prefix on branches prevents ambiguity with identically-named tags.

Key rules:
- The tag MUST live on `main` — never on a feature/release branch.
- One tag per package per release.
- Bump the `version` field in the package's `pyproject.toml` as part of the release branch work (not at merge time).
- Always use **annotated tags** (`git tag -a`), never lightweight tags. Annotated tags record the tagger, date, and message — lightweight tags are just pointers with no metadata.

### Beta releases

While v1 is in beta, the rules above have one exception. Every package shares one PEP 440
version (`1.0.0b1`, `1.0.0b2`, and so on), all `pyproject.toml` versions bump together and are
re-locked with `uv lock`, and each beta gets one suite tag, `v1.0.0bN`, instead of one tag per
package. The scoped `<package-name>/v<semver>` tags return for independent releases after v1.0.0.
Betas promise no compatibility with each other.

A beta has no release branch. It is released in three steps:

1. Open a pull request into `next` that bumps every `pyproject.toml` version and re-locks with
   `uv lock`, for example from a `chore/bump-1.0.0bN` branch.
2. Merge `next` into `main` with a merge commit, not a squash, so that `next` never diverges
   from `main`. Tag the merge commit on `main` with an annotated `v1.0.0bN` tag.
3. Publish a GitHub prerelease for the tag.

```
feat/*, fix/*, chore/bump-* ──PR──▶ next ──●──●──●
                                                 │ merge commit
main ────────────────────────────────────────────●  tag v1.0.0bN
```

After v1.0.0, releases return to the per-package release branches described above. Until then,
do not use `make release-branch`, which branches from `origin/main` and is meant for that stable
flow.

### Release Make Target

```bash
make release-branch PKG=engine VER=0.2.1   # Create branch (release/metis-engine/v0.2.1)
```

Use `PKG=<name>` for workspace packages (`packages/`) or `APP=<name>` for apps (`apps/`).

## Support and contributions during the beta

Issues and pull requests are welcome. We handle them on a best-effort basis: we read them, but we
do not promise response times, and a pull request may wait a while for review.

The beta supports one path: the toy app, then Langfuse, then `metis wizard`, then
`metis engine`, then `metis insights`. A bug that breaks this path is the first thing we fix, and
it is the only kind of fix that we hold a beta for. Everything else is recorded as an issue and
considered for a later beta. Anything outside the path is experimental, so a report or a pull
request about it may be deferred.

Before you open a pull request for a larger change, open an issue first and describe what you
want to do. That saves you work if the change does not fit the path or conflicts with something in
progress. Expect breaking changes between betas, because no compatibility is promised.

Report a security problem privately, as [SECURITY.md](SECURITY.md) describes, and not in a public
issue.

## Getting Help

- Architecture questions → [docs/architecture.md](docs/architecture.md)
- Build system → `make help`
- CLI usage → `metis --help`
- Support and what to expect → [Support and contributions during the beta](#support-and-contributions-during-the-beta)

If something in this guide is unclear or outdated, open an issue or fix it directly — contributions to docs are contributions too.
