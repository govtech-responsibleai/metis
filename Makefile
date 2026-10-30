.PHONY: install-docs run-docs build-docs check-docs generate-grader-docs install-landing run-landing build-landing run-site build-site help install install-wizard install-engine install-api install-web install-extras install-extras-playwright run run-api run-web lint lint-fix format format-check fix typecheck check check-env ci test test-unit format-check-web typecheck-web test-web build-web check-api-web check-web clean release-branch

help:
	@printf "Available targets:\n"
	@printf "\n"
	@printf "Install:\n"
	@printf "  make install                     Install all workspace dependencies (including dev group)\n"
	@printf "  make install-wizard              Install metis-wizard only\n"
	@printf "  make install-engine              Install metis-engine + Playwright browser\n"
	@printf "  make install-api                 Install metis-api only\n"
	@printf "  make install-web                 Install apps/web dependencies from its lockfile\n"
	@printf "  make install-docs                Install website dependencies from its lockfile\n"
	@printf "  make install-landing             Install landing-page dependencies from its lockfile\n"
	@printf "  make install-extras              Install all optional extras\n"
	@printf "  make install-extras-playwright   Install Playwright Python package + Chromium binary\n"
	@printf "\n"
	@printf "Run (development servers):\n"
	@printf "  make run                  Show instructions for starting all services\n"
	@printf "  make run-web              Start the API server and the web dev server together\n"
	@printf "  make run-api              Start the API server on port 8001 only\n"
	@printf "  make run-site             Start the landing page and the docs together\n"
	@printf "  make run-docs             Start the docs on port 3000 only\n"
	@printf "  make run-landing          Start the landing page on port 8443 only\n"
	@printf "\n"
	@printf "Code quality:\n"
	@printf "  make lint              Run Ruff lint checks\n"
	@printf "  make lint-fix          Apply Ruff lint autofixes\n"
	@printf "  make format            Format all Python files with Ruff\n"
	@printf "  make format-check      Check formatting without modifying files\n"
	@printf "  make fix               Apply lint autofixes and format\n"
	@printf "  make typecheck         Run Pyright type checking\n"
	@printf "  make check             Run lint + format-check + typecheck (non-mutating)\n"
	@printf "  make check-env         Check .env keys and connectivity (metis doctor)\n"
	@printf "  make test              Run all tests\n"
	@printf "  make test-unit         Run unit tests only\n"
	@printf "  make ci                Full CI suite: check + web checks + test\n"
	@printf "  make check-web         Run non-mutating apps/web checks\n"
	@printf "  make check-docs        Check links and build the docs\n"
	@printf "  make build-docs        Build the docs site\n"
	@printf "  make build-landing     Build the landing page\n"
	@printf "  make build-site        Build the GitHub Pages site into _site/ (landing page + docs)\n"
	@printf "  make generate-grader-docs  Regenerate the grader data that the docs read\n"
	@printf "\n"
	@printf "Other:\n"
	@printf "  make clean             Remove all generated/cached files\n"
	@printf "  make release-branch    Create a release branch (PKG=<name>|APP=<name> VER=<semver>)\n"

install:
	uv sync --all-packages --group dev --extra test
	$(MAKE) install-web

install-wizard:
	uv sync --package metis-wizard

install-engine:
	uv sync --package metis-engine
	$(MAKE) install-extras-playwright

install-api:
	uv sync --package metis-api

install-web:
	npm --prefix apps/web ci

install-docs:
	npm --prefix website ci --omit=optional

run-docs:
	npm --prefix website start

build-docs:
	npm --prefix website run build

check-docs: build-docs

install-landing:
	pnpm --dir landing-page install --frozen-lockfile

run-landing:
	pnpm --dir landing-page dev

build-landing:
	pnpm --dir landing-page build

# Both site servers, as build-site builds both. They run on separate ports, so the published
# layout of /metis/ and /metis/docs/ is only visible in build-site output.
# The landing page waits until the docs answer, so the landing-page address is the last line at startup.
run-site:
	@scripts/run-dev.sh \
		"docs=npm --prefix website start" \
		"landing=until curl -so /dev/null http://127.0.0.1:3000/metis/docs/; do sleep 0.5; done; pnpm --dir landing-page dev"

# GitHub Pages serves the landing page at /metis/ and the docs at /metis/docs/.
build-site: build-landing build-docs
	rm -rf _site
	cp -R landing-page/dist _site
	cp -R website/build _site/docs

generate-grader-docs:
	uv run python packages/library/scripts/generate_grader_docs.py

install-extras: install-extras-playwright

install-extras-playwright:
	uv sync --all-packages --group dev --extra test --extra playwright
	uv run playwright install --with-deps chromium

run:
	@printf "Start the API server and the web dev server:\n"
	@printf "  make run-web    # API server on port 8001 and web dev server\n"
	@printf "\n"
	@printf "Or start the API server only:\n"
	@printf "  make run-api    # API server on port 8001\n"

# Each line of output carries its service label, Ctrl-C stops the servers, and a server that stops
# on its own takes the other one with it. To start the API server only, use run-api.
# The web server waits until the API answers, so the web address is the last line at startup.
run-web:
	@scripts/run-dev.sh \
		"api=HOST=127.0.0.1 PORT=8001 uv run metis-api" \
		"web=until curl -so /dev/null http://127.0.0.1:8001/; do sleep 0.5; done; npm --prefix apps/web run dev"

run-api:
	HOST=127.0.0.1 PORT=8001 uv run metis-api

format-check-web:
	npm --prefix apps/web run format:check

typecheck-web:
	npm --prefix apps/web run typecheck

test-web:
	@temp_dir=$$(mktemp -d); \
	trap 'rm -rf "$$temp_dir"' EXIT; \
	ln -s "$$(pwd)/apps/web/node_modules" "$$temp_dir/node_modules"; \
	METIS_WEB_TEST_CACHE_DIR="$$temp_dir/cache" npm --prefix apps/web test

build-web:
	npm --prefix apps/web run build

check-api-web:
	npm --prefix apps/web run check:api

check-web: format-check-web typecheck-web test-web check-api-web

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

format-check:
	uv run ruff format . --check

fix:
	$(MAKE) lint-fix
	$(MAKE) format

typecheck:
	uv run pyright

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit/

check:
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck

check-env:
	uv run metis doctor

ci:
	$(MAKE) check
	$(MAKE) check-web
	$(MAKE) build-web
	$(MAKE) test
	$(MAKE) -C packages/core check-schema

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache .pyright .mypy_cache _site
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# --- Release workflow -----------------------------------------------------------

# Resolve component name and directory from PKG= or APP=
ifdef PKG
  ifdef APP
    $(error Set PKG or APP, not both)
  endif
  COMPONENT := $(PKG)
  COMPONENT_DIR := packages/$(PKG)
  FULL_NAME := metis-$(PKG)
else ifdef APP
  COMPONENT := $(APP)
  COMPONENT_DIR := apps/$(APP)
  FULL_NAME := metis-$(APP)
else
  COMPONENT :=
  COMPONENT_DIR :=
  FULL_NAME :=
endif

define check_release_args
	@if [ -z "$(COMPONENT)" ]; then \
		printf "Error: Set PKG=<name> (for packages/) or APP=<name> (for apps/)\n"; \
		printf "  Example: make $@ PKG=engine VER=0.2.1\n"; \
		printf "  Example: make $@ APP=api VER=1.0.0\n"; \
		exit 1; \
	fi
	@if [ -z "$(VER)" ]; then \
		printf "Error: Set VER=<semver>\n"; \
		printf "  Example: make $@ PKG=$(COMPONENT) VER=0.2.1\n"; \
		exit 1; \
	fi
	@if [ ! -d "$(COMPONENT_DIR)" ]; then \
		printf "Error: Directory $(COMPONENT_DIR) does not exist\n"; \
		exit 1; \
	fi
endef

RELEASE_BRANCH := release/$(FULL_NAME)/v$(VER)

release-branch:
	$(check_release_args)
	@if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
		printf "Error: Working tree is not clean. Commit or stash changes first.\n"; \
		exit 1; \
	fi
	git fetch origin main
	git checkout -b "$(RELEASE_BRANCH)" origin/main
	@printf "Created and switched to branch: $(RELEASE_BRANCH)\n"
	@printf "\n"
	@printf "Next steps:\n"
	@printf "  1. Update $(COMPONENT_DIR)/pyproject.toml — bump version to \"$(VER)\"\n"
	@printf "  2. Run: uv lock\n"
	@printf "  3. Push the branch: git push -u origin $(RELEASE_BRANCH)\n"
