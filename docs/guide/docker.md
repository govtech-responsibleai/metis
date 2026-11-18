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
| Build and run without Compose | `make docker-build`, then `make docker-run` |
| Copy an input folder into the volume | `docker compose cp my-input metis:/data/my-input` |
| Run a simulation | `docker compose exec metis metis engine simulate --project-dir /data --input-dir /data/my-input` |
| Make the report | `docker compose exec metis metis insights report --results-file /data/experiments/execute/<experiment>/results.json` |

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
METIS_ADMIN_TOKEN=<a long random value>
```

Then make a user account for each person. See
[Turn on login for a shared server](wizard/api.md#turn-on-login-for-a-shared-server).

## Settings

The container reads `.env`. The model variables are the same as for a local install. The image
contains no key and no `.env` file.

| Variable | Purpose |
|---|---|
| `METIS_LOGIN` | `1` turns login on. |
| `METIS_ADMIN_TOKEN` | The token that makes and lists user accounts. |
| `METIS_DATABASE_URL` | The SQLAlchemy URL of the database. The default is the SQLite file in `/data`. |
| `METIS_API_CONNECTION_CHECK` | `1` turns on the connection check of the web app. It is off in the container. |

With the connection check on, the server sends a request to each target URL that a user enters.
This includes internal addresses that only the server can reach.

The container always listens on port 8000. `HOST` and `PORT` in `.env` have no effect. To use
another port on your computer, change the first number of `ports` in `docker-compose.yml`.

## Data

All data is in the `metis-data` volume, which the container mounts on `/data`. Back up this
volume to keep your data.

| Path | Content |
|---|---|
| `/data/metis.db` | The database |
| `/data/experiments/design/` | The files of each Target |
| `/data/experiments/execute/` | The experiment folders |
| `/data/users/<user id>/` | The same folders for each user account, when login is on |

The container runs as the user `metis` with uid 10001.

## Run one container

Run exactly one METIS container, with one API process. Do not add workers, replicas, or
autoscaling. The API does not support more than one process, for three reasons:

- The database is a SQLite file in `/data`. A second container has its own volume, so it has its
  own database.
- The experiment folders are on the volume of one container. They are the source of truth for
  every run.
- The API keeps the run that is alive now in memory. A second process does not know about it.
  It can start a second run of the same experiment, and it answers a stop or status request as
  if no run were alive.

A second process on the same volume is not safe either. The store locks a save only inside its
own process, so saves from two processes can mix.

Check these settings on a hosting platform:

| Setting | Value |
|---|---|
| Instances or replicas | 1 |
| Autoscaling | Off |
| Deploy strategy | Stop the old container before the new one starts. A rolling deploy runs two containers on one volume for a short time. |
| Start command | `metis-api`, the `CMD` of the image. Do not start the API with Uvicorn or Gunicorn directly. |

More CPUs do not need more processes. The API requests are small, and the engine run spends most
of its time waiting for model calls.

## Certificates

A proxy that intercepts TLS causes `CERTIFICATE_VERIFY_FAILED` errors during the build. The
Dockerfile already uses the system certificates in both stages. If your proxy has its own root
certificate, add that certificate in both stages of the Dockerfile, before the step that
downloads packages.
