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

Shared agent skills are in `.agents/skills/`, which Codex reads. To use them in Claude Code, copy
them to `.claude/skills/`, and run the command again after a pull that changes a skill:

```bash
mkdir -p .claude/skills && cp -R .agents/skills/. .claude/skills/
```

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

Branch off the branch your pull request targets with a descriptive prefix. That is `next` while v1
is in beta and `main` after v1.0.0:

| Prefix | Use |
|--------|-----|
| `feat/` | New functionality |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `refactor/` | Code restructuring (no behavior change) |
| `test/` | Adding or improving tests |

Example: `feat/langfuse-ingester`, `fix/score-validation`

During the beta, open your pull request against `next`, except for the documentation fixes
described below, which branch off `main` and target it.

While v1 is in beta, `main` is the branch we present to users, and the published site is built from
`main` alone. A change under `website/` that corrects or clarifies something
already in the latest beta therefore goes to `main`, so it does not have to wait for the next
release. Documentation for anything that exists only on `next` stays on `next` with its code, and
all other work goes to `next`.

After a pull request lands on `main`, merge `main` into `next` with a merge commit before the next
release. This keeps `next` from missing anything `main` has, so the release merge does not turn into
a conflict.

An urgent fix goes to `next` like any other fix, followed by an early beta release (see "Beta
releases"). If `next` holds work that is not ready to ship, open the pull request against `main`
instead, tag the fix as a new beta, and merge `main` into `next` the same day so the fix is not
lost from the next release.

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

### Running the Landing Page and Docs

The public site has two parts, each with its own Node project: the landing page in
`website/landing-page/` and the docs in `website/docs-site/`. The docs need Node.js 22 or later and use npm, which
comes with Node. The landing page uses [pnpm](https://pnpm.io/), which Node does not include, so
install it first with `corepack enable pnpm` or `brew install pnpm`. CI uses pnpm 11. If pnpm is
missing, the landing page targets stop and say so.

```bash
make install-landing    # once: install website/landing-page dependencies (needs pnpm)
make run-landing        # landing page dev server on port 8443
make build-landing      # production build into website/landing-page/dist

make install-docs       # once: install docs dependencies
make run-docs           # docs dev server on port 3000
make build-docs         # production build into website/docs-site/build
make check-docs         # build the docs and check links

make run-site           # both dev servers together
make build-site         # both builds, laid out into _site/ as GitHub Pages serves them
```

`make install-extras` installs both sets of dependencies, along with Playwright. See
[`website/docs-site/README.md`](website/docs-site/README.md) for more on previewing the docs.

### Commit Messages

We follow a convention for commit messages [borrowed from Deis/CoreOS/AngularJS](https://github.com/deis/deis/blob/master/CONTRIBUTING.md#commit-style-guideline). The format is:

```
{type}({scope}): {subject}

{body}

{footer}
```

**Rules:**

- `{type}` is one of: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- `{scope}` is the affected package or app name (e.g., `core`, `engine`, `wizard`, `api`), or
  `release` for a release step that touches every package (see "Merging")
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
- [ ] It links an issue, unless it is one of the pull requests that need none (see "Issues and
      milestones")

### What Reviewers Look For

- Adherence to the dependency DAG (no upward imports)
- Type annotations on public APIs
- Focused scope — one concern per PR

### Issues and milestones

Every pull request that changes behaviour or adds a feature links an issue, and the milestone is
set on that issue, not on the pull request (see "Milestones"). A milestone then counts each piece
of work once, and the link records which pull request delivered it.

These pull requests need no issue, and get no milestone:

| Pull request | Why |
|--------------|-----|
| Version bump (`chore/bump-1.0.0bN`) | It is a step of the release |
| `next` into `main`, and `main` into `next` | It moves work that is already tracked |
| Small fixes, such as typos and broken links | The pull request describes itself |

A milestone lists planned work, and the GitHub release notes list everything that shipped, these
pull requests included.

`Closes #N` closes an issue only when the pull request targets the default branch, `main`. Close an
issue by hand, with a link to the pull request, when its pull request merges into `next`.

### Merging

PRs require at least one approval. CI must pass.

Squash-merge every feature, fix, and documentation PR, so each one lands as a single commit whose
title is the PR title. Write the PR title as a Conventional Commit with a package scope, because
that title becomes the commit on the target branch.

The exception is a PR that carries one long-lived branch into another. While v1 is in beta, the
release merge of `next` into `main` and the merge of `main` into `next` are always merge commits,
never squashes (see "Beta releases"). A squash would drop the link between the two branches, and
the next merge between them would replay the same changes and raise conflicts.

Release pull requests have two exceptions to the title rule. The release pull request from `next`
into `main` is titled `release/vX.Y.Z`, matching its release issue (see "Milestones"). Its title
does not become the first line of the commit, because it is merged with a merge commit. The
`release` scope is reserved for release steps that touch every package: the version bump,
`chore(release): bump the version to X.Y.Z`, and the merge back,
`chore(release): merge main into next after vX.Y.Z`.

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

A beta has no release branch. It is released in four steps:

1. Open a pull request into `next` that bumps every `pyproject.toml` version and re-locks with
   `uv lock`, from a `chore/bump-1.0.0bN` branch and titled
   `chore(release): bump the version to 1.0.0bN`. Every beta needs this pull request,
   because `metis --version`, `metis doctor` and the API docs page read the version from these
   files. Update the version in the Status section of `README.md` in the same pull request.
2. Check the version on `next` after the pull request is merged.
   `git grep -n '^version = ' -- '*pyproject.toml'` must show `1.0.0bN` on each of its 8 lines,
   and `uv lock --check` must pass.
3. Merge `next` into `main` through a pull request titled `release/v1.0.0bN`, with a merge
   commit, not a squash, so that `next` never diverges from `main`. Its body says
   "Part of #N", naming the release issue, not "Closes #N", because the release issue stays open
   until the last step. Tag the merge commit on `main` with an annotated `v1.0.0bN` tag. Do not
   tag a commit whose files show a different version.
4. Publish a GitHub prerelease for the tag, with "Generate release notes".

```
feat/*, fix/*, chore/bump-* ──PR──▶ next ──●──●──●
                                                 │ merge commit
main ────────────────────────────────────────────●  tag v1.0.0bN
```

After v1.0.0, releases return to the per-package release branches described above. Until then,
do not use `make release-branch`, which branches from `origin/main` and is meant for that stable
flow.

### Milestones

Each planned release has a milestone, which holds the plan, and a release issue, which points
users to it. Every tag also gets a GitHub release, which records what shipped.

| Term | What it is | Example |
|------|------------|---------|
| **Tag** | Marks a commit that has shipped | `v1.0.0b3` |
| **GitHub release** | Publishes a tag with notes on what shipped | the `v1.0.0b3` prerelease |
| **Milestone** | Groups the issues planned for one release, and holds the planned release notes | `v1.0.0b4` |
| **Release issue** | Points users to the milestone, and tells its subscribers when the plan changes | `release/v1.0.0b4` |

#### One milestone per planned release

A release is planned when the work in it is chosen before it is tagged. Major, minor and beta
releases are planned. Patch releases usually are not, because they ship fixes that have already
landed.

| Release | Example | Milestone | Release issue | GitHub release |
|---------|---------|-----------|---------------|----------------|
| Major | `v2.0.0` | yes | yes | yes |
| Minor | `v1.1.0` | yes | yes | yes |
| Beta | `v1.0.0b4` | yes | yes | yes, as a prerelease |
| Patch | `v1.0.4` | only if planned | only if planned | yes |

- A milestone has the same name as its tag: `v1.0.0b4`, `v1.0.0`, `v1.1.0`.
- A patch that is planned ahead, such as a batch of fixes to announce, gets a milestone like any
  other planned release.
- Create a milestone when you first assign an issue to it.
- Set its due date to the date the release is expected to ship, and change it when that date
  moves.
- Write the planned release notes in its description, in the shape below. The description is the
  only copy of the notes, so a change of plan is made there and nowhere else. Its first line says
  when the plan was last updated, because GitHub keeps no history of milestone descriptions.
- Set milestones on issues, not on pull requests (see "Issues and milestones" under Pull
  Requests).
- Close a milestone when its tag ships. Move its unfinished issues to the next milestone first.
- `backlog` is the one milestone that is not a tag. It holds triaged work with no release chosen,
  and it never closes.

The milestone description follows this skeleton:

```markdown
Plan last updated: YYYY-MM-DD. Discussion and updates: #N (the release issue).

## What's coming

Two to four sentences on the theme of this release and why it matters to users. Write for users:
say what they will be able to do, not which files change.

## Highlights

The changes users will notice most, each with a sentence on what it does and a link to its issue.

## Breaking changes

What users must change when they upgrade, and how. Betas promise no compatibility with each other,
so list every change that breaks a command, a file format or a config. Write "None." if there are
none.
```

The issue list below the description is the full list of planned work, so the notes describe
themes and changes rather than list every issue.

#### One release issue per milestone

The milestone holds the plan. The release issue gives users a place to find it, to be told when it
changes, and to ask about it, none of which a milestone offers: it cannot be pinned or subscribed
to, and it takes no comments.

- Open it from the Release template, [`.github/ISSUE_TEMPLATE/release.md`](.github/ISSUE_TEMPLATE/release.md).
  The template sets the title and label, but GitHub templates cannot set a milestone, so set it
  after submitting. The template appears to everyone who opens a new issue, and its description
  marks it as for maintainers only.
- Title: `release/vX.Y.Z`, the same as its release pull request, with the `release` label and the
  milestone of the same name.
- Body: a sentence on what the release is for and a link to the milestone. The notes stay in the
  milestone, so the issue body rarely changes.
- When the plan changes in a way users would notice, update the milestone description and its
  "Plan last updated" line, then post a one-line comment on the release issue that says what
  changed, such as "Moved #273 to v1.0.0b5." The comment notifies subscribers, and the comments
  together are the history of the plan.
- Pin the release issue of the next release so that users see it first.
- Assign it to the maintainer who runs the release. The assignee makes sure every box in its
  Shipping checklist is ticked before closing the issue. Whoever does a step, such as the
  version-bump pull request, may tick its box.
- Close it when the tag ships, with a link to the GitHub release.
- Its issues are not sub-issues of it. The milestone is the one list of planned work in a release.

The template's Shipping checklist lists every step in "Beta releases", so that the release issue
shows which steps are done. Change the two together.

#### A GitHub release for every tag

Publish a GitHub release for every tag, using "Generate release notes". Mark betas as
prereleases. The release is how users learn what shipped: anyone who watches the repository's
releases is notified, and a tag alone notifies no one.

No `CHANGELOG.md` is kept during the beta, because the GitHub releases do that job.

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
