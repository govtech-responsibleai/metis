# Docker guide

One image serves the web app and the API on port 8000. It also has the `metis` command.

## Quick start

Run these commands from the repository root.

1. Make the environment file. Then set your model keys in it. See [the model guide](models.md).

   ```bash
   cp .env.example .env
   ```

2. Build the image and start the container.

   ```bash
   docker compose up -d --build
   ```

3. Open `http://localhost:8000` in a browser.

## Commands

| Task | Command |
|---|---|
| Build the image and start the container | `docker compose up -d --build` |
| Read the logs | `docker compose logs -f metis` |
| Stop the container | `docker compose stop` |
| Remove the container and keep the data | `docker compose down` |
| Remove the container and the data | `docker compose down -v` |
| Build and run without Compose | `make docker-build`, then `make docker-run`. See [Make targets](#make-targets). |
| Copy an input folder into the volume | `docker compose cp my-input metis:/data/my-input` |
| Run a simulation | `docker compose exec metis metis engine simulate --project-dir /data --input-dir /data/my-input` |
| Make the report | `docker compose exec metis metis insights report --results-file /data/evaluations/experiments/<experiment>/outputs/reports/results.json` |

`my-input` is a folder on your computer that holds `specification.yaml` and `fixtures/`. Replace
`<experiment>` with the name of the experiment folder. Give `--project-dir /data` to the `metis`
command, so that the output goes into the volume.

The image has no Playwright browser. A target that the engine reaches through a web UI cannot
run in this container.

## Login

Login is off by default. Then anyone who can reach port 8000 can read and change every Target.
Use this default on a trusted network only.

To turn login on, set these variables in `.env` and start the container again.

```bash
METIS_LOGIN=1
METIS_JOIN_TOKEN=<a long random value>
METIS_ADMIN_TOKEN=<a different long random value>
METIS_ADMIN_USERNAME=<your username>
METIS_ADMIN_PASSWORD=<a long random password>
```

Participants type the join token on the login page to make their own user accounts. It can do
nothing more. The admin token is for your own scripts, and has the power of an admin. Never give
it to participants. Set both admin variables or neither. At each start, the container makes your
admin user account or sets its password. Login has no limit on the number of tries, so use a
long random password, for example from `openssl rand -hex 16`.

Log in, select your username at the foot of the left rail, then select **Manage accounts**. Only
an admin sees this item. On this page you can make a user account, reset a password, and delete a
user account with all its Targets and Experiments. A new password shows one time, so copy it
before you close the dialog. You cannot delete your own user account or the admin of `.env`.

If you forget your admin password, change `METIS_ADMIN_PASSWORD` and start the container again.

From a script, send the admin token in an `Authorization: Bearer` header:

```bash
curl http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $METIS_ADMIN_TOKEN"
```

For the API routes, see
[Turn on login for a shared server](wizard/api.md#turn-on-login-for-a-shared-server).

Each new user account gets a demo Target. To let a person start an experiment from it, also
set `TOYAPP_API_URL` in `.env`.

To let participants use the METIS CLI on their own computers, name the variables that they need
in `METIS_WORKSHOP_ENV`, for example
`METIS_WORKSHOP_ENV=LANGFUSE_PUBLIC_KEY,LANGFUSE_SECRET_KEY,LANGFUSE_BASE_URL`. Each participant
then selects their username, then **CLI settings**, and copies the `.env` lines. Each user
account can read these values, so never list a model provider key or a `METIS_` variable.

## Settings

The container reads `.env`. The model variables are the same as for a local install. The image
contains no key and no `.env` file.

| Variable | Purpose |
|---|---|
| `METIS_LOGIN` | `1` turns login on. |
| `METIS_JOIN_TOKEN` | The token that participants use to make user accounts. |
| `METIS_ADMIN_TOKEN` | The token of your scripts. It has the power of an admin. |
| `METIS_ADMIN_USERNAME` | The username of your admin user account. |
| `METIS_ADMIN_PASSWORD` | The password of your admin user account. |
| `METIS_WORKSHOP_ENV` | The variables that each user account can copy for the METIS CLI, separated by commas. |
| `METIS_DATABASE_URL` | The SQLAlchemy URL of the database. The default is the SQLite file in `/data`. |
| `METIS_API_CONNECTION_CHECK` | `1` turns on the connection check of the web app. It is off in the container. |
| `METIS_API_ENGINE_MAX_RUNS` | The experiments that run at the same time. The default is 4. |

With the connection check on, the server sends a request to each target URL that a user enters.
This includes internal addresses that only the server can reach.

The container listens on port 8000. Compose and `make docker-run` set `HOST` and `PORT` after
`.env`, so a `PORT` there has no effect. A platform that gets `.env` as environment variables does
not do this, so leave `PORT` and `HOST` out of the variables you give it. To use another port on
your computer, change the first number of `ports` in `docker-compose.yml`.

## Experiments at the same time

The server runs up to `METIS_API_ENGINE_MAX_RUNS` experiments at the same time, for all users.
An experiment that starts when every place is taken waits in a queue, first in first out. Its
page shows Queued and the number of experiments before it. It starts on its own when a place
frees, and its evaluate starts on its own when its simulate ends. No browser tab must stay open.

Choose the value from the rate limits of your model provider and of the target. Every run calls
the same provider, and most often the same target. Each run makes up to its concurrency of calls
at the same time, so the server makes up to `METIS_API_ENGINE_MAX_RUNS` × concurrency calls at
the same time. If runs fail with rate-limit errors, lower the value.

To check a value before a workshop, run the load test. It starts a number of experiments at the
same moment, follows them to the end, and says yes or no:

```bash
METIS_API_ENGINE_MAX_RUNS=4 make run-api      # in one terminal
make load-test LOAD_TEST_USERS=60             # in another, from the same folder
```

The load test runs against an API on your computer, not against the container. It writes a copy
of the input folder for each user into the project folder of the API, and the project folder of
the container is in the volume. Each copy has its own Specification id, so no two starts share an
experiment folder. Start the API with the same `.env` and the same value of
`METIS_API_ENGINE_MAX_RUNS` as the server. Login must be off.

The verdict is yes only when every start is accepted, every experiment ends completed after its
evaluate, and the status route answers 95 % of its requests in under one second. The report also
gives the queue wait and the run time of each user. They are not part of the verdict, because a
long wait beyond `METIS_API_ENGINE_MAX_RUNS` is the queue at work. The exit code is 0 for yes and
1 for no. On Ctrl-C or at the timeout, the load test stops every experiment that it started.

Each run is real. It makes the model and target calls of N experiments, three trials each with the
default input, and their evaluations. The input copies stay in `evaluations/load-test/` and the
experiments in `evaluations/experiments/`, and the report prints both paths.

| Variable | Default | Purpose |
|---|---|---|
| `LOAD_TEST_USERS` | 4 | The experiments to start at the same moment. |
| `LOAD_TEST_URL` | `http://127.0.0.1:8001` | The address of the API, as `make run-api` starts it. |
| `LOAD_TEST_INPUT` | `packages/engine/examples/http-agentic_eval_toyapp-1` | The input folder to copy for each user. |
| `LOAD_TEST_TIMEOUT` | 1800 | Seconds for the whole test. A timeout gives no. |
| `LOAD_TEST_PROJECT_DIR` | as `metis-api` finds it | The project folder of the API, when the API runs from another folder. |

The queue is in the memory of the server. When the container restarts, the queue is lost, and
no queued experiment starts on its own. A queued new experiment then shows Stopped. A queued
resume shows the state from before it, for example Waiting for evaluate. In both cases, Resume
starts it again.

## Make targets

`make docker-build` and `make docker-run` take these variables.

| Variable | Default | Purpose |
|---|---|---|
| `IMAGE_TAG` | `metis:<commit>` | The image that `docker-build` makes and `docker-run` starts. |
| `PLATFORM` | this machine | The platform to build for. Most servers need `linux/amd64`. |
| `ENV_FILE` | `.env` | The env file that the container reads. |
| `CA_BUNDLE` | none | A CA bundle that `docker-run` mounts. See [Certificates](#certificates). |

```bash
# Build and run on this computer.
make docker-build
make docker-run

# Build for a server, then push the image.
IMAGE_TAG="<registry>/metis:$(git rev-parse --short HEAD)"
make docker-build PLATFORM=linux/amd64 IMAGE_TAG="$IMAGE_TAG"
docker push "$IMAGE_TAG"
```

Replace `<registry>` with the address of your container registry.

`docker-run` reads `ENV_FILE` with `docker run --env-file`, which keeps quotes as part of a value.
It stops when a value in the file is in quotes, so remove those quotes first.

`docker-run` starts the image and does not build it. Run `make docker-build` again after a
change to the code.

## Data

All data is in the `metis-data` volume, which the container mounts on `/data`. Back up this
volume to keep your data.

| Path | Content |
|---|---|
| `/data/evaluations/metis.db` | The database |
| `/data/evaluations/interviews/` | The Interview of each Target |
| `/data/evaluations/specifications/` | The Specification of each Target |
| `/data/evaluations/experiments/` | The experiment folders |
| `/data/users/<user id>/evaluations/` | The Interviews, Specifications and experiments of each user account, when login is on. The database stays in `/data/evaluations/`. |
| `/data/users/<user id>/user.json` | The username and the login times of each user account, for debugging. It holds no password. |

The container runs as the user `metis` with uid 10001.

## Run one container

Run exactly one METIS container, with one API process. Do not add workers, replicas, or
autoscaling. The API does not support more than one process, for three reasons:

- The database is a SQLite file in `/data`. A second container has its own volume, so it has its
  own database.
- The experiment folders are on the volume of one container. They are the source of truth for
  every run.
- The API keeps the runs that are alive now, and the queue, in memory. A second process does not
  know about them. It can start a second run of the same experiment, it answers a stop or status
  request as if no run were alive or queued, and it has a queue and a run limit of its own.

A second process on the same volume is not safe either. The store locks a save only inside its
own process, so saves from two processes can mix.

Check these settings on a hosting platform:

| Setting | Value |
|---|---|
| Instances or replicas | 1 |
| Autoscaling | Off |
| Deploy strategy | Stop the old container before the new one starts. A rolling deploy runs two containers on one volume for a short time. |
| Start command | `metis-api`, the `CMD` of the image. Do not start the API with Uvicorn or Gunicorn directly. |

More CPUs do not need more processes. The API requests are small, and the engine runs spend most
of their time waiting for model calls. To run more experiments at the same time, raise
`METIS_API_ENGINE_MAX_RUNS`. See [Experiments at the same time](#experiments-at-the-same-time).

## Certificates

Behind a proxy that intercepts TLS, model calls from the container fail with
`CERTIFICATE_VERIFY_FAILED`, and the web app reports that the model could not return a usable
result. Give `make docker-run` the CA bundle that your computer trusts:

```bash
make docker-run CA_BUNDLE="$SSL_CERT_FILE"
```

The container then trusts that bundle in place of the image's bundle. The image itself trusts the
Debian bundle only, so the same image runs on a server that has no proxy. Do not build the proxy's
CA into an image that you deploy.

The same proxy can also cause `CERTIFICATE_VERIFY_FAILED` errors during the build. The Dockerfile
already uses the system certificates in both stages. If your proxy has its own root certificate,
add that certificate in both stages of the Dockerfile, before the step that downloads packages,
and do not deploy that image.
