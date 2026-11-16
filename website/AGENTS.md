# Website — Codebase Guide

## Overview

`website/` contains everything that is published to GitHub Pages:

- **`docs-site/`** — the Docusaurus documentation site, served at `/metis/docs/`.
- **`landing-page/`** — the marketing landing page (Vite + React + Tailwind), served at `/metis/`.

Each sub-project has its own `package.json` and its own package manager (npm for the docs,
pnpm for the landing page).

## Design guide

See [`docs/design.md`](../docs/design.md) for the brand colours, typography, and UI rules that
govern both the documentation site and the landing page.

## Directory structure

```
website/
├── AGENTS.md
├── docs-site/                 # Docusaurus project root
│   ├── docusaurus.config.js   # Plugins, theme, navbar
│   ├── sidebars.js            # Sidebar structure
│   ├── package.json           # Docs dependencies (npm)
│   ├── src/                   # Custom components, CSS, theme overrides
│   │   ├── theme/             # Swizzled Docusaurus components
│   │   ├── components/        # Custom React components
│   │   ├── css/               # Site-wide tokens (custom.css)
│   │   ├── data/              # graders.json
│   │   └── glossary/          # Glossary parsing logic + tests
│   ├── static/                # Static assets (images served at site root)
│   └── docs/                  # Documentation content
│       ├── *.md / *.mdx       # Documentation pages
│       ├── assets/            # Images used in docs
│       └── library/           # Grader reference pages
└── landing-page/              # Marketing landing page (pnpm)
    ├── AGENTS.md
    ├── src/
    └── public/
```

## Import conventions

Components and data in `src/` are imported with the `@site` Docusaurus alias:

```js
import Glossary from '@site/src/components/Glossary';
```

The `@examples` alias maps to `packages/engine/examples/` for importing example YAML files.

## Commands

```bash
make install-docs          # Install docs dependencies (from lockfile, --omit=optional)
make run-docs              # Start the docs dev server on port 3000
make build-docs            # Build the docs site
make check-docs            # Check links and build the docs

make install-landing       # Install landing-page dependencies (from lockfile)
make run-landing           # Start the landing page dev server on port 8443
make build-landing         # Build the landing page

make run-site              # Both servers together
make build-site            # Combined build into _site/ (landing page + docs)
```

## See also

- [`landing-page/AGENTS.md`](landing-page/AGENTS.md) — landing page specifics
