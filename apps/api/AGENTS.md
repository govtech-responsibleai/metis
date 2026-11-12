# metis-api

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

IMPORTANT: Always talk in ASD-STE100 Simplified Technical English.

## Package Purpose

A thin HTTP door over the wizard's public Interview interface, plus a store of Interview
records and their files. The wizard routes translate request and response JSON
and status codes and hold no user state. Every interview rule stays inside metis-wizard; this
package must not learn any of them.

## The client-held state boundary

The wizard routes keep only immutable settings and model clients for the process lifetime. They keep
no Specification, pending request, or Interview state. Each lifecycle operation carries the required
state in the request body and the next state goes back whole in the response. Any instance can
therefore serve any operation, and the wizard routes never write an Interview file. Do not add
per-user state to the wizard routes; if an operation needs to remember something, it belongs in the
returned `InterviewState`, not on the app.

## The store

The database has one `interviews` table. Each row holds the existing Interview record as JSON,
with its id and save time. The state contains the Target details and Specification.
The `targets` route name identifies these saved Interviews. It does not require a separate Target
table. Saving an Interview does not compile its Specification or prepare an engine input folder.
The compile and package routes keep their existing roles.

The store routes save what a client wants to keep. They do not call the wizard routes, and the
wizard routes do not use the store.

| Route | Purpose |
|---|---|
| `GET /api/v1/targets` | List saved Interview summaries, newest first, and unreadable rows. |
| `DELETE /api/v1/targets/{target_id}` | Delete the Interview record and its files. |
| `GET /api/v1/targets/{target_id}/interview` | Read the Interview record. |
| `PUT /api/v1/targets/{target_id}/interview` | Save the record and its new files. |
| `GET /api/v1/targets/{target_id}/interview/files/{name}` | Read one file of the record. |

The PUT of an Interview is a multipart form. The `record` part is a file that contains the
record JSON. Each new file is a part named `files`, and its file name is the name in the record.
The files of the record are its fixtures and the files of an answer that the wizard has not
accepted yet. The store keeps them in one folder, by name. Each file of the record has its own
name, by the identity of `records.file_name_identity` (NFC, then upper case, then lower case). A
record with two files of the same name gets 400 `validation_error`. `store.safe_name` applies the
portable name rule of the web app (`normalizeFixtureName` in `apps/web/src/fixture-policy.ts`),
so keep the two rules the same. A file that the store already has needs no part. After the save,
the store keeps only the files that the record refers to.

`put_interview` does three steps in a fixed order. It writes the new files into the fixture
folder, saves the row, and then deletes the files that the record no longer refers to. Thus a
saved record always has all its files. The store has no recovery step. A save that stops before
its last step can leave a file that no record refers to, and the next save of that Interview
deletes it. The store writes each upload under a temporary name first. A new file with the name
of a file in the folder moves that file to a backup name, then takes the name. A save that fails
puts each backup back, so it changes no file of the saved record.

The file route sends each file as an attachment with `X-Content-Type-Options: nosniff`. The
media type is the type in the record when a header can hold it, else `application/octet-stream`.

Each Store holds a thread lock for the full time of a save or a delete, so the owner check and
the write stay together. The store has no lock between processes.

Before a first save, the store checks both the row and the Target folder. A folder with no row is
already owned by another tool, so PUT returns 409 `target_exists` and leaves it unchanged. When a
first save fails, the store removes the folder that it made. DELETE requires a row. When no row
exists, it returns 404 `not_found` and leaves any folder unchanged. A delete removes the row and
then the Target folder.

Settings:

- `metis-api --project-dir PATH` names the project folder. The folder must exist. Without the
  option, the API uses the rule of `metis engine simulate`: the nearest folder at or above the
  working directory that has a `pyproject.toml`, else the working directory.
  The rule is `metis.core.execution_layout.find_project_root`, which the engine also calls.
- `METIS_DATABASE_URL` is a SQLAlchemy URL. The default is
  `sqlite:///<project>/experiments/metis.db`. The tables use only portable SQL, so do not add
  SQLite-only types, JSON1 functions, or `INSERT OR REPLACE`.

`cli.py` gives Uvicorn the app object from `create_app(project_dir=...)`, so the app keeps the
project folder of the command. The store builds its paths from the constants in `store.py`.

The files of a Target are in the layout that `metis wizard init` writes, under
`<project>/experiments/design/<target_id>/`. The web app gives a new Target the id
`YYYYMMDD-HHMMSS-interview`, which is the name of a `metis wizard init` folder. When the id is
taken, the web app adds `-2`, `-3`, and so on. The `created_at` of the record tells one Interview
from another. A save with the id of another Interview gets 409 `target_exists` and changes
nothing. `inputs/fixtures/` holds the files that the user uploads. A missing row or file gets 404
`not_found`. A row that this version cannot read gets 409 `unreadable_record` and shows in the
`problems` list of `GET /api/v1/targets`.

## Module layout

```
src/metis/api/
├── main.py            the app composition root: /health, routers, the store, and error handlers
├── routes/graders.py  read-only installed grader catalogue route
├── routes/models.py   read-only model role status route
├── routes/wizard.py   client config, Interview lifecycle, compile, and package routes
├── routes/targets.py  store routes for Interview records and files
├── records.py         the wire models of the store routes
├── store.py           the store: rows through SQLAlchemy, files in experiments/design/
├── tables.py          the portable tables of the store
├── settings.py        environment-backed settings and the production dependency composition
├── cli.py             the `metis-api` executable and its --project-dir option
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
It also gives each test a store in its own project folder under `tmp_path`.

Cover the door contract with representative cases: status mapping, the stable failure body,
a wizard Interview across two app instances that writes no file, the store routes, shared Interview saves across two app instances, the generated OpenAPI discriminators, package archive
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
