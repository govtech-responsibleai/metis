# metis-api

See root [AGENTS.md](../../AGENTS.md) for monorepo-wide instructions.

IMPORTANT: Always talk in ASD-STE100 Simplified Technical English.

## Package Purpose

A thin HTTP door over the wizard's public Interview interface, plus a store of Targets,
Interview records, Specifications, and Experiments. The wizard routes translate request and response JSON
and status codes and hold no user state. Every interview rule stays inside metis-wizard; this
package must not learn any of them.

The API also reads the experiment folders under the project folder, the same folder as the store.
It holds no report rules. metis-insights builds the reports.

## The client-held state boundary

The wizard routes keep only immutable settings and model clients for the process lifetime. They keep
no Specification, pending request, or Interview state. Each lifecycle operation carries the required
state in the request body and the next state goes back whole in the response. Any instance can
therefore serve any operation, and the wizard routes never write an Interview file. Do not add
per-user state to the wizard routes; if an operation needs to remember something, it belongs in the
returned `InterviewState`, not on the app.

## The store

The store prepares a missing completed Specification on its first read.
An Interview that cannot compile gives a per-record error and remains available for editing.

A saved record has two parts: rows in the database and files in a project folder. `Store`
writes the two parts together. A `Store` object works for one user account, `Store.user_id`:
it reads and writes only the Targets of that user account. `Store(url, project_dir)` works for
the local user account, which owns each record when login is off. `Store.for_user` gives a
`Store` for a different user account on the same database and lock. Its files are in
`users/<user id>/` of the server project folder, with the layout of a project folder inside.
A route gets its store from `get_store` only, which gives the `Store` for the user account that
the login guard found. Do not read `app.state.store` in a route.

The `targets` table is the one table that names the user account. The other tables link to
`targets.id`. `Store._owns` is the one place that finds a Target for a request, and it reads
only the Targets of its user account. Thus a record of another user account gets 404
`not_found`, as a record that does not exist. A save with the Target id of another user account
gets 409 `target_exists`. Two user accounts can have an Experiment folder with the same name,
so the key of an Experiment row is its Target and its folder name together. The report routes read the
Experiment folders of the project folder of the user account.

The store starts from a new database. It has no step that changes the tables of an earlier
version.

The store routes save what a client wants to keep. They do not call the wizard routes, and the
wizard routes do not use the store.

| Route | Purpose |
|---|---|
| `GET /api/v1/targets` | List the Targets, newest first, and the rows that cannot be read. |
| `DELETE /api/v1/targets/{target_id}` | Delete the rows and the store folder of a Target. |
| `GET /api/v1/targets/{target_id}/interview` | Read the Interview record. |
| `PUT /api/v1/targets/{target_id}/interview` | Save the record and its new files. |
| `GET /api/v1/targets/{target_id}/interview/files/{name}` | Read one file of the record. |
| `GET /api/v1/targets/{target_id}/specification` | Read the last Specification and its input folder. |
| `GET /api/v1/targets/{target_id}/experiments` | List the Experiments of a Target. |
| `GET`, `PUT`, `DELETE /api/v1/experiments/{experiment_id}` | Read, save, or delete one Experiment row. |

The web app starts an Experiment in two requests. It sends the `input_dir` of the Specification,
a path relative to the project folder, to `POST /api/v1/engine/simulate`. Then it saves the row
with `PUT /api/v1/experiments/{experiment_id}` and the step `simulate`. The engine does not know
the Target. The row is the only link between the Target and its Experiment.

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
folder, saves the rows, and then deletes the files that the record no longer refers to. Thus a
saved record always has all its files. The fixture folder has no recovery step. A save that stops before
its last step can leave a file that no record refers to, and the next save of that Interview
deletes it. The store writes each upload under a temporary name first. A new file with the name
of a file in the folder moves that file to a backup name, then takes the name. A save that fails
puts each backup back, so it changes no file of the saved record.

The file route sends each file as an attachment with `X-Content-Type-Options: nosniff`. The
media type is the type in the record when a header can hold it, else `application/octet-stream`.

Each Store holds a thread lock for the full time of a save or a delete, so the owner check and
the write stay together. The store has no lock between processes.

The API supports one process and one instance only. The store lock is a thread lock, the
default database is a SQLite file in the project folder, the experiment folders are on one
disk, and `EngineRuns` keeps the live runs and the queue in memory. None of them is shared
between processes.
`metis-api` gives Uvicorn the app object, so it cannot start more than one worker. Uvicorn or
Gunicorn started directly on `create_app` can, so the deployment docs require `metis-api`. Do not add
code that assumes a second process. See
[Run one container](../../docs/guide/docker.md#run-one-container).

A folder in `evaluations/interviews/` with a state file that validates is an Interview of the
wizard CLI. The store adds its rows when it opens and at each Target list. Such a row has no
transcript, and its file references are the files in its `documents/` folder.

Before a first save, the store checks the row, the Interview folder, and the Specification
folder. A folder with no row has no Interview state that the store can read, so PUT returns 409
`target_exists` and leaves it unchanged. When a first save fails, the store removes both folders
that it made. DELETE requires a row. When no row exists, it returns 404 `not_found` and leaves
any folder unchanged. A delete removes the row, then the Interview folder and the Specification
folder.

Settings:

- `metis-api --project-dir PATH` names the project folder. The folder must exist. Without the
  option, the API uses the rule of `metis engine simulate`: the nearest folder at or above the
  working directory that has a `pyproject.toml`, else the working directory.
  The rule is `metis.core.project_layout.find_project_root`, which the engine and the wizard
  CLI also call.
- `METIS_DATABASE_URL` is a SQLAlchemy URL. The default is
  `sqlite:///<project>/evaluations/metis.db`. With login on, the database stays in the
  `evaluations/` folder of the server project folder, and that folder holds no other files. The tables use only portable SQL, so do not add
  SQLite-only types, JSON1 functions, or `INSERT OR REPLACE`.

`cli.py` gives Uvicorn the app object from `create_app(project_dir=...)`, so the app keeps the
project folder of the command. The store builds its paths from the constants in `store.py`.

The files of a Target are in the layout that `metis wizard init` writes, in two folders with the
Target id as their name: `<project>/evaluations/interviews/<target_id>/` and
`<project>/evaluations/specifications/<target_id>/`. The Target id follows the `<id>` rule of
`metis.core.project_layout.ID`. The web app gives a new Target the id
`YYYYMMDD-HHMMSS-interview-<random>`, the same form as a `metis wizard init` id. The random
part is five characters, so two people who start in the same second get different ids. When the id is
taken, the web app adds `-2`, `-3`, and so on. The `created_at` of the record tells one Interview
from another. A save with the id of another Interview gets 409 `target_exists` and changes
nothing. `interview_state.json` in the Interview folder holds the state of the Interview, in the
file that the wizard CLI uses. The Interview row holds the other parts of the record, and each
read takes the state from the file. `documents/` in the Interview folder holds the files that the
user uploads, in the folder of the CLI opening documents. The Specification folder is the folder
for `metis engine simulate --input-dir`. Each save of a done Interview compiles the
Specification, then writes the Specification row and the Specification folder again. The folder
comes from the `specifications/<id>/` files of the package archive, and a new folder replaces the
old one in two renames. The staged and old folders sit next to it in `specifications/` for the
time of the save. A save is all or nothing: a
compile failure gets 400 `compilation_failed` and changes nothing. A missing row or file gets 404
`not_found`. A row that this version cannot read gets 409 `unreadable_record` and shows in the
`problems` list of `GET /api/v1/targets`.

## Engine routes

The engine routes start, stop, and follow the engine steps of an experiment. They call the
`metis.engine.run` library functions in the API's own process. Each job runs on a
`threading.Thread` of its own. They start no child process, and they do not use the store. They
read and write the experiment folders only, as `metis engine simulate` and `evaluate` do.

Each engine route works in the project folder of the request, which `request_project_dir` in
`experiment_dirs.py` gives. The report routes use the same function. With login off, it is the
project folder of the server. With login on, it is `users/<user id>/`, so a user account
reaches only its own experiments, and an experiment of another user account gets 404
`experiment_not_found`. `login_guard` refuses a request with no login session, so the engine
routes have no login check of their own.

The experiment folders on disk are the source of truth. In memory, `EngineRuns` keeps only
the runs that are alive or queued now. A run has its project folder, its experiment id and
folder, its steps, its stop flag (a `threading.Event`), and the last `seq` of
`logs/events.jsonl` when the start was accepted. Two user accounts can have an experiment
folder with the same name, so a run is the run of a request only when its project folder and
its experiment id are both the same. When the thread ends, the API forgets the run.

The API runs up to `METIS_API_ENGINE_MAX_RUNS` jobs at the same time, across all experiments of
all user accounts. A start that finds every slot taken gets 202 and waits in a queue, first in
first out. It starts when a slot frees. A start never fails because the engine is busy. Each
simulation sends its logs to its own files, and each evaluation reads the target's Langfuse
through a client of its own. The METIS-internal tracing client is the same for all runs. One
lock covers the check for a live or queued run, the checks of the start, the queue, and the
start of each thread. A refused start therefore creates no folder, and two starts of the same
experiment cannot both pass. A restart loses the queue, and no queued job starts after it. A
queued new simulation has a folder with no events, so the web app shows it as Stopped, with
Resume. A queued resume or evaluate shows the last state of its folder, for example Waiting for
evaluate, and its Resume starts it again.

A job is what one start asks for. One thread runs all the steps of a job in order, so the
evaluate after a simulate keeps the slot of its simulate. A step runs only when the stop flag
is clear. A simulate that stops or fails ends the job, so the evaluate does not run.

| Route | Steps of the job |
|---|---|
| `POST /api/v1/engine/simulate` | `simulate`, then `resume_evaluation` |
| `POST /api/v1/engine/simulate/{experiment_id}/resume` | `resume_simulation`, then `resume_evaluation` |
| `POST /api/v1/engine/evaluate/{experiment_id}` | `evaluate` |
| `POST /api/v1/engine/evaluate/{experiment_id}/resume` | `resume_evaluation` |

The evaluate after a simulate is `resume_evaluation` with `command="run"`, as
`metis engine run --resume`. A simulate that ran trials deleted the evaluation outputs, so it
grades every trial. A resume that ran no trial keeps a complete evaluation, and the evaluate
writes only its `evaluating` lines. It uses the `concurrency` and `langfuse_timeout` settings,
because the simulate request has no evaluate fields.

| Route | Purpose |
|---|---|
| `POST /api/v1/engine/simulate` | Create an experiment from an input folder, run its trials, and grade them. |
| `POST /api/v1/engine/simulate/{experiment_id}/resume` | Run again the trials that did not end, and grade the trials with no evaluation. |
| `POST /api/v1/engine/evaluate/{experiment_id}` | Delete the earlier evaluation and grade every trial (`evaluate`). A complete evaluation needs `regrade: true`. |
| `POST /api/v1/engine/evaluate/{experiment_id}/resume` | Grade the trials with no evaluation file (`resume_evaluation`). |
| `POST /api/v1/engine/{experiment_id}/stop` | Set the stop flag of the run, or remove a queued run from the queue. |
| `GET /api/v1/engine/{experiment_id}` | The phase, the status, and the counts of the experiment. |
| `GET /api/v1/engine/{experiment_id}/events?after=<seq>` | The lines of `logs/events.jsonl` after `seq`. |
| `GET /api/v1/doctor` | The checks of `metis doctor`. |

Each start and stop returns 202 `{experiment_id}` at once. The `input_dir` of a new
simulation is relative to the project folder of the request. The API resolves it, symbolic links included,
and refuses a path that is absolute or outside the project folder. `concurrency` and
`langfuse_timeout` take their default from a setting when a request leaves them out.

The id of the Specification is the first part of the name of the experiment folder,
`evaluations/experiments/<specification id>-<YYYYmmdd-HHMMSS>/`. The id field accepts any text, so
an id with `/`, `\`, or `..` would name a folder in another place, for example in the project
folder of another user account. Before `prepare_experiment` makes a folder, the simulate route
reads the id and refuses an id that is empty, `.`, `..`, or that holds `/`, `\`, or a NUL
character. After `prepare_experiment`, the route also checks that the new folder is directly in
`evaluations/experiments/` of the request. #174 gives the id field this rule in metis-core, for the
wizard and the CLI too.

A full evaluate deletes the results of the experiment before it grades again. Thus the evaluate
route refuses an experiment whose evaluation is complete, with 409 `evaluation_complete`, and
keeps the results. The evaluation is complete when `results.json` loads
(`evaluation_is_complete`). To grade a complete evaluation again, send `regrade: true` in the
body. The evaluate that the server starts after a simulate does not use this route, so this
check does not apply to it, and it needs no `regrade`. The web app never sends `regrade`. The
evaluate resume route has no `regrade` field, and a complete evaluation gives it 409
`evaluation_complete` too.

Every check of a start runs in the request, before the job is accepted. The routes check in
this order and return the first error:

| Route | Order of the checks |
|---|---|
| `simulate` | `validation_error`, `input_dir_outside_project`, `invalid_langfuse_timeout`, `engine_stopping`, `invalid_inputs` or `experiment_exists` |
| resume, evaluate | `validation_error`, `experiment_not_found`, `engine_stopping`, `run_in_progress`, `invalid_experiment`, `invalid_langfuse_timeout`, `evaluation_complete` (evaluate and evaluate resume) |
| stop | `experiment_not_found`, `no_run` |
| status, events | `validation_error` (events only), `experiment_not_found` |

| Status | Code | When |
|---|---|---|
| 404 | `experiment_not_found` | No folder in `evaluations/experiments/` has the id. |
| 422 | `input_dir_outside_project` | `input_dir` is absolute, holds a NUL character, or is outside the project folder. |
| 422 | `invalid_inputs` | The Specification id is not one folder name, or `prepare_experiment` refuses the inputs or the project folder. For the id, the message is the text of the API; else it is the engine text. |
| 409 | `experiment_exists` | A run of the same Specification started in the same second. |
| 409 | `run_in_progress` | A start for an experiment that runs now or waits in the queue. |
| 422 | `invalid_experiment` | The folder has no `specification/` snapshot, or uses the earlier layout. The message is the text of `resolve_experiment_dir`. |
| 422 | `invalid_langfuse_timeout` | `TraceWaitSettings.from_env` refuses the timeout. The simulate routes check the timeout setting, for the evaluate after the simulate. |
| 409 | `evaluation_complete` | A resume of an evaluation whose `results.json` loads. |
| 409 | `no_run` | A stop for an experiment that does not run and does not wait in the queue. |
| 503 | `engine_stopping` | A start after the shutdown started. The start makes no folder. It is the only engine error with `retryable: true`. |
| 422 | `validation_error` | A field is not valid, or `concurrency` or `langfuse_timeout` is more than its maximum setting. |

A run that fails after the 202 fails on its thread, and frees its slot for the next job. The
engine has then already ended the events log with `failed` and its reason, or with `interrupted`
for a stop. The API logs any error that is not a `RunError` or `RunStopped`. The text of a run
goes to `logs/console.log` of the experiment, never to the stdout of the API.

The status route takes its answer from `EngineRuns` when the run of that id is queued or alive.
A queued run is `queued`, with the phase of its first step and no counts. `queue_ahead` is the
number of jobs before it in the queue, across all user accounts, so 0 means that it starts next.
It is a count only, and it never names an experiment or a user account. It is `null` in every
other status. A live run is `running`, or `stopping` once the stop flag is set. Its phase is the
phase of its newest phase line with a `seq` more than the start `seq`, so a job that moves from
simulate to evaluate reports `evaluating`. Before its first line, the phase is that of its first
step. The counts come from the `started` line of that phase after the start `seq`, so they are
`null` until the engine writes it. When no run is alive, the answer comes from the last phase
line of the events log: `completed`, `failed` with its reason, or `interrupted`. A log that ends
with `started` is `unfinished`, because the run ended with no last line, for example after the
process was killed. A log with no phase line is `not_started`. The status route and the events
route read the file with one reader (`read_events`). It skips a last line with no newline and
any line that does not parse. The events route returns each line as the engine wrote it.

Startup and shutdown:

- Before the first request, the lifespan calls `setup_engine_process` one time. It loads
  `.env`, calls `tracing_key()`, and calls `configure_logging()`. `METIS_LOG_LEVEL` sets the
  level, which also decides what reaches the per-trial log files of a simulation.
- At shutdown, the lifespan empties the queue, sets the stop flag of each run, and waits for
  the threads, for at most `METIS_API_STOP_TIMEOUT` seconds in all. No queued job starts after
  that, and a new start gets 503 `engine_stopping`. Each run thread is a daemon thread, so a run
  that does not stop in time cannot keep the process open.

Settings, which the API reads at startup. A value that is not a whole number of 1 or more
stops the start.

| Variable | Default | Sets |
|---|---|---|
| `METIS_API_ENGINE_CONCURRENCY` | 1 | The `concurrency` of a request that gives none. |
| `METIS_API_ENGINE_MAX_CONCURRENCY` | 8 | The largest `concurrency` of a request. |
| `METIS_API_LANGFUSE_TIMEOUT` | 180 | The `langfuse_timeout` in seconds of a request that gives none, and of the evaluate after a simulate. It is longer than the 90 of `--langfuse-timeout`, because the evaluate starts as soon as the simulate ends, while the last traces still reach Langfuse. A session whose traces have settled waits only for its first check. |
| `METIS_API_MAX_LANGFUSE_TIMEOUT` | 600 | The largest `langfuse_timeout` of a request. |
| `METIS_API_STOP_TIMEOUT` | 30 | The seconds that the shutdown waits for all runs to stop. |
| `METIS_API_ENGINE_MAX_RUNS` | 4 | The jobs that run at the same time. A start beyond it waits in the queue. |

Each run calls the same model provider, and most often the same target. The rate limits of the
provider and of the target, more than METIS, set the right value of `METIS_API_ENGINE_MAX_RUNS`.
Each run makes up to `concurrency` calls at the same time, so the server makes up to
`METIS_API_ENGINE_MAX_RUNS` × `concurrency` calls at the same time.

`GET /api/v1/doctor` returns each `DoctorResult` of `metis.core.doctor.run_doctor()` as
`{name, status, detail, fix}`, in display order. It holds no check rule.

## User accounts and login

Login is off by default, and then the API has no user accounts. `METIS_LOGIN=1` turns login on.
Use the glossary terms "user account" and "login session".

| Route | Purpose |
|---|---|
| `POST /api/v1/users` | Make a user account and return its credentials. The join token can also call it. |
| `GET /api/v1/users` | List the user accounts. |
| `POST /api/v1/users/{username}/password` | Give a user account a new password and end its login sessions. |
| `DELETE /api/v1/users/{username}` | Delete a user account with its Targets and its project folder. |
| `POST /api/v1/auth/login` | Check the credentials and set the login cookie. |
| `POST /api/v1/auth/logout` | End the login session. |
| `GET /api/v1/auth/me` | Tell if login is on, and name the current user account and if it is an admin. |
| `GET /api/v1/workshop/env` | Give the variables of `METIS_WORKSHOP_ENV` that have a value, for the `.env` of the METIS CLI. |

The user routes need the admin token or the login session of an admin.

`routes/accounts.py` holds `login_guard`, the one place that decides if a request can reach a
route. When login is on, each `/api` route needs a login session, except the paths in
`_OPEN_PATHS` and the paths under `/api/v1/users`. A new router gets this rule with no code of
its own. Do not add a login check to a route. Add a path to `_OPEN_PATHS` only when another
secret protects it, or when the route changes only the login session of its own cookie, as
logout does. Each route on `users_router` must depend on `get_caller`, because the guard does
not check those paths. A test checks that each of them refuses a request with no credentials.
The guard also
refuses a request that changes data from a page of another origin. It reads `Sec-Fetch-Site`,
and `Origin` for a browser that does not send it. Do not compare with `Host` when
`Sec-Fetch-Site` is present, because a proxy can change `Host`.

`accounts.py` makes the credentials. A username is an adjective and an animal. A password is
ten characters from an alphabet with no characters that look alike. A person cannot choose or
change them, so each password is random and login needs no rate limit. Keep that rule, or add
a rate limit. The one exception is the admin of the environment: the operator chooses its
password, with no length rule. A login checks the password in its own case, then in lower case.
The `users` table keeps a scrypt hash. The `password_hash` column can be empty, for
a user account of a later login method. For debugging, `users/<user id>/user.json` holds the id,
the username, and the times of creation, last login, and last write. `Accounts` writes it with
mode 0600 when it makes the user account and at each correct login, and a write that fails is
only logged. Do not add the password or its hash to the file: a copy of the server folder must
not be enough to log in. The `login_sessions` table keeps the SHA-256 of the cookie value, never
the value. Records link to the id of a user account, never to its username.

An admin is a user account with a row in the `admins` table. It is a separate table because
`create_all` never adds a column to the `users` table of an earlier database.

`get_caller` is the one rule of the user routes. It returns the `UserAccount` of the login
session, `Token.ADMIN`, or `Token.JOIN`. A request with an `Authorization` header uses only its
token, and `get_caller` does not read the cookie. An unknown token gets 401 `invalid_token`.
`require_admin` lets through an admin and the admin token, and gives 403 `admin_required` to the
others. With login off, each user route returns 404.

The join token in `METIS_JOIN_TOKEN` can only make user accounts that are not admins. Do not
give it another power, because each participant knows it. The admin token in
`METIS_ADMIN_TOKEN` is for the scripts of the facilitator. It has the power of an admin on the
user routes, and it opens no other route. The API does not start when the two tokens are the
same, or when a token is set and login is off.

`METIS_ADMIN_USERNAME` and `METIS_ADMIN_PASSWORD` name the admin of the environment. Set both or
neither. At each start, `Accounts.ensure_admin` makes that user account or sets its password,
and makes it an admin. A changed password ends its login sessions.

`METIS_WORKSHOP_ENV` names variables, separated by commas. At startup, `_lifespan` reads their
values from `Settings.env`, which includes the project `.env`, and leaves out a name with no
value. `routes/workshop.py` returns them in the same order, and 404 `not_found` when the
setting is unset. Each user account with a login session can read them, so the login guard is
their only protection. Do not add the route to `_OPEN_PATHS`. The API does not start when the
setting is set and login is off, or when it has a name that is not a variable name.

`Store.delete_user_account` holds the lock of a save and deletes the rows of the user account in
one transaction, then its folder `users/<user id>/`. The route checks in this order: 404
`not_found`, then 409 `cannot_delete_self`, `environment_admin`, `local_account`, and
`run_in_progress`. The run check is last, because only it can pass at a later try.
`run_in_progress` covers a run that waits in the queue too, because it would start later in the
folder. `EngineRuns.idle_in` holds the lock of the runs for the full delete, so a run cannot
start or join the queue in the folder.

## Module layout

```
src/metis/api/
├── main.py            the app composition root: /health, routers, the store, and error handlers
├── routes/graders.py  read-only installed grader catalogue route
├── routes/models.py   read-only model role status route
├── routes/reports.py  experiment report routes, as JSON and as the HTML page
├── routes/wizard.py   client config, Interview lifecycle, compile, and package routes
├── routes/targets.py  store routes for Targets, Interview records, files, and Specifications
├── routes/experiments.py  store routes for Experiment rows
├── routes/engine.py   engine routes: start, resume, evaluate, stop, status, and events
├── routes/doctor.py   the checks of `metis doctor`
├── engine_runs.py     the live and queued engine jobs, their threads, and the events reader
├── experiment_dirs.py the project folder of a request, and an experiment folder from its id
├── errors.py          RouteError, which the app maps to the service error shape
├── routes/accounts.py user and auth routes, and the login guard of all /api routes
├── routes/workshop.py the workshop variables for the .env of the METIS CLI
├── accounts.py        user accounts and login sessions: credentials, hashes, and rows
├── records.py         the wire models of the store routes
├── store.py           the store: rows through SQLAlchemy, files in evaluations/interviews/ and specifications/
├── tables.py          the portable tables of the store
├── input_folder.py    builds, stages, and swaps the input folder of a Specification
├── settings.py        environment-backed settings and the production dependency composition
├── web.py             serves the built web app in metis/api/web_dist
├── cli.py             the `metis-api` executable and its --project-dir option
└── __init__.py        version and the re-exported core version
```

The dependency arrows are `apps/api -> metis.wizard`, `apps/api -> metis.insights`, and
`apps/api -> metis.engine`. The wizard
router calls `handle_interview`,
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

The report routes find an experiment id among the folder names in
`<project folder>/evaluations/experiments/`, so an id cannot name another path.
`GET /api/v1/experiments/{experiment_id}/report` returns `report.json`, and
`GET /api/v1/experiments/{experiment_id}/report.html` returns `report.html`. Both are the same
report in two formats. Both responses are inline, with the file name in `Content-Disposition`, so a
client that wants a file saves the response. Both call `metis.insights.ensure_report`, which builds
the files when they are missing or older than `results.json`. An unknown id gives 404
`experiment_not_found`. An experiment with no `results.json` gives 409 `results_missing`, and an
experiment whose report cannot be built gives 409 `report_build_failed`.

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
a wizard Interview across two app instances that writes no file, the store routes, the input
folder through the engine gate, the generated OpenAPI discriminators, package archive
contents and validation, and one offline Interview start/turn/end-to-`/compile` end-to-end validated
through the engine gate. Do not repeat every driver example.

The engine route tests use `FakeEngine` from `tests/fixtures/api/engine.py` in place of the
engine library functions, so no test runs a trial, calls a model, or reaches the network. The
checks before a run starts are the real library functions on folders under `tmp_path`.

## Package-Specific Notes

- The client implementation guide is `docs/guide/wizard/api.md`. Keep its state loop and examples
  aligned with the OpenAPI document when the HTTP contract changes.
- The API resolves the interview role through `metis.core.model_settings`, with the
  same variable names as the wizard and the engine. `cli.py` reads the one `.env` that core finds.
  For monorepo development, keep one active `.env` at the repository root. Copy it from the
  root `.env.example`. See
  [the model guide](../../docs/guide/models.md).
- The root `Dockerfile` builds one image with the API, the `metis` CLI, and the built web app.
  Build it from the repository root with `docker build -t metis .`. METIS is one uv workspace
  with a single lockfile, so the build needs the workspace root and the path-dependency members.
  The image copies the web build into `metis/api/web_dist` inside the API package. The container
  runs `metis-api --project-dir /data` under `tini`, as one process, so the API serves the web
  app on its own address (`metis.api.web`). The API serves that folder when it has an
  `index.html`. Without it, the API runs alone. The web route does not match a path under
  `/api`, so the API routes keep their 404 and 405 responses. See
  [the Docker guide](../../docs/guide/docker.md).
