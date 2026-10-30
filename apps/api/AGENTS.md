# metis-api

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

IMPORTANT: Always talk in ASD-STE100 Simplified Technical English.

## Package Purpose

A thin, stateless HTTP door over the wizard's public Interview interface. It translates request and
response JSON and status codes and holds no user state. Every interview rule stays inside
metis-wizard; this package must not learn any of them.

## The client-held state boundary

The service keeps only immutable settings and model clients for the process lifetime. It keeps no
Specification, pending request, or Interview state — each lifecycle operation carries the required state
in the request body and the next state goes back whole in the response. Any instance can therefore
serve any operation, and no Interview file is ever written. Do not add per-user server state; if an
operation needs to remember
something, it belongs in the returned `InterviewState`, not on the app.

## Module layout

```
src/metis/api/
├── main.py            the app composition root: /health, routers, and error handlers
├── routes/graders.py  read-only installed grader catalogue route
├── routes/models.py   read-only model role status route
├── routes/wizard.py   client config, Interview lifecycle, compile, and package routes
├── settings.py        environment-backed settings and the production dependency composition
├── cli.py             the `metis-api` executable (Uvicorn on metis.api.main:app)
└── __init__.py        version and the re-exported core version
```

The dependency arrow is `apps/api -> metis.wizard`. The router calls `handle_interview`,
`compile_specification`, and `package_specification` from the `metis.wizard` facade and maps typed results
onto an HTTP status (200/400/422/503/500) in one error shape. No stage, Specification, prompt, matching,
fixture validation, or compilation rule lives here.

`GET /api/v1/graders` is a stateless catalogue route owned by `routes/graders.py`. It reads stable
`GraderSummary` values from the public wizard facade only. It does not read Interview state or write
files.

`GET /api/v1/models` returns the model name, the configured status, the score effect, and the
missing variable names of each LLM role. It never returns a key or a URL. The API starts when model
settings are missing. Then each Interview route returns 503 `model_unavailable`, with the missing
variables, the `.env` path, and the model guide path in the message.

`GET /api/v1/wizard/config` returns package-owned opening copy, working status, and perspective
definitions from the public wizard facade. The API transports this text but does not own or copy it.

## Testing

The API's unit tests live under `tests/unit/api/` and its end-to-end tests under
`tests/integration/api/`, in the root `tests/` tree.

API tests are door tests: they prove the HTTP adapter preserves wizard behaviour, not the wizard
rules themselves. They reuse the wizard's own offline corridor — the `ScriptedInterviewer`, the
`walk` driver, and the hand-authored specifications under `tests/fixtures/wizard/` — through the
`send` transport, so the door and the wizard's Slice B gate share one answer script. `conftest.py`
injects the scripted dependency pair, so no test builds the real gateway or reaches the network.

Cover the door contract with representative cases: status mapping, the stable failure body,
statelessness across two app instances, the generated OpenAPI discriminators, package archive
contents and validation, and one offline Interview start/turn/end-to-`/compile` end-to-end validated
through the engine gate. Do not repeat every driver example.

## Package-Specific Notes

- The client implementation guide is `docs/guide/wizard/api.md`. Keep its state loop and examples
  aligned with the OpenAPI document when the HTTP contract changes.
- The API resolves the interview role through `metis.core.model_settings`, with the
  same variable names as the wizard and the engine. `cli.py` reads the one `.env` that core finds.
  For monorepo development, keep one active `.env` at the repository root. Copy it from the
  root `.env.example`. See
  [the model guide](../../docs/guide/models.md).
- Build the image from the repository root: `docker build -f apps/api/Dockerfile -t metis-api .`.
  METIS is one uv workspace with a single lockfile, so the build needs the workspace root and the
  path-dependency members.
