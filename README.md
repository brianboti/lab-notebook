# Lab Notebook

A lab notebook for experiments: people create experiments, attach files, move them from planned to running to done,
and follow an activity feed. Programs use the same data through a JSON API. It is the reference "complicated" app for
[Lab Deploy](https://github.com/brianboti/lab-deploy) and uses everything the platform provides:

| Platform feature | How the app uses it |
|---|---|
| Postgres (`needs.database: postgres`) | Experiments, attachments and activity, through the Cloud SQL Python connector with IAM sign-in (no password) |
| Migration job (`needs.migrate`) | `alembic upgrade head` runs before visitors move to a new version |
| Bucket (`needs.buckets: [uploads]`) | Attachment files (`BUCKET_UPLOADS`) |
| Topic (`needs.topics: [events]`) | Every change is published; the Activity page pulls the subscription and stores what it reads |
| Secret (`secrets: [API_KEY]`) | Programs present `X-API-Key` to create or delete through the API |
| Settings (`env`) | `APP_TITLE`, `LOG_LEVEL`, `MAX_UPLOAD_MB` |
| Sign-in in front of the app | `authenticated` today (Google identity tokens); `lab-members` puts Google sign-in in front for people |

## Pages and API

| Path | What it is |
|---|---|
| `/` | Dashboard with counts and recent experiments |
| `/experiments`, `/experiments/new`, `/experiments/{id}` | List and search, create, detail with status, attachments and delete (owner only) |
| `/activity` | The activity feed, read from Pub/Sub when the page opens |
| `/whoami` | Who you are and which backends the service is using |
| `/health` | Readiness: answers 200 without touching the database, bucket or topic |
| `GET /api/stats`, `GET /api/experiments`, `GET /api/experiments/{id}`, `GET /api/whoami` | Reads |
| `POST /api/experiments`, `DELETE /api/experiments/{id}` | Writes; need `X-API-Key` |

## Run it locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=sqlite:///./local.db API_KEY=local-key
alembic upgrade head
uvicorn app.main:app --reload --port 8080
```

Without `BUCKET_UPLOADS` and `TOPIC_EVENTS` the app keeps files and events in memory. Tests: `python -m pytest`.
Lint: `ruff check .`.

## Dependencies

`requirements.txt` pins the direct dependencies; `requirements.lock` pins the whole tree with hashes and is what the
image installs. After changing `requirements.txt`:

```bash
uv pip compile requirements.txt --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_28 -o requirements.lock
```

## Migrations

Add a file under `migrations/versions/`. Keep each one compatible with the version still serving (add first, remove
later), because the migration runs before the new version takes traffic and a rollback returns to the old code.

Tested end to end on Lab Deploy staging (2026-10-13): onboarding, migrations, rollback, failures and cancel.
