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
| `/data/evaluations/metis.db` | The database |
| `/data/evaluations/interviews/` | The Interview of each Target |
| `/data/evaluations/specifications/` | The Specification of each Target |
| `/data/evaluations/experiments/` | The experiment folders |
| `/data/users/<user id>/evaluations/` | The Interviews, Specifications and experiments of each user account, when login is on. The database stays in `/data/evaluations/`. |
| `/data/users/<user id>/user.json` | The username and the login times of each user account, for debugging. It holds no password. |

Run only one container on a volume. The container runs as the user `metis` with uid 10001.

## Certificates

A proxy that intercepts TLS causes `CERTIFICATE_VERIFY_FAILED` errors during the build. The
Dockerfile already uses the system certificates in both stages. If your proxy has its own root
certificate, add that certificate in both stages of the Dockerfile, before the step that
downloads packages.
