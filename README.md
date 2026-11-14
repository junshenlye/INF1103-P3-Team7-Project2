# Project 2

A Python domain-model project for representing trimester projects, submitted modules, source documents, assessment facts, and document-processing state. The models separate the data and rules used to build assessment schedules from the surrounding application or persistence layer.

## Project structure

- `src/models/projects/` — project and submitted-module identities.
- `src/models/documents/` — document references, staged documents, and extracted source elements.
- `src/models/assessments/` — assessment types and schedule construction.
- `src/models/processing/` — processing jobs, lifecycle rules, outcomes, snapshots, and checkpoints.
- `src/config/` — shared application limits.
- `src/serialization/` — strict JSON decoding helpers.
- `tests/` — automated tests for the models and supporting utilities.
- `integrations/github_actions_notifier/` — optional Telegram alerts for pull requests, reviews, issues, and completed CI runs.

## Run the tests

The test suite uses Python's standard-library `unittest` runner:

```sh
python -m unittest discover -s tests -v
```

Run the command from the repository root. A successful run reports each test and ends with an `OK` summary.

See [tests/README.md](tests/README.md) for linting, the frontend and browser checks, running everything with `python scripts/test.py`, and running the suite in Docker.

## Optional Telegram notifications

See [integrations/github_actions_notifier/README.md](integrations/github_actions_notifier/README.md) to enable the opt-in GitHub Actions notifier. It requires Telegram bot and group secrets; without them, its scheduled workflow runs the mock-based unit tests and skips outbound notifications.

## Apply database migrations

With the dependencies from `requirements.txt` installed and the settings from `.env.example` set in the environment, apply any pending PostgreSQL migrations from the repository root:

```sh
python -m src.migrate
```

Migrations in `database/migrations/` run in filename order inside one transaction, and already applied scripts are skipped, so the command is safe to repeat. It exits with status 1 and an error on stderr if settings are missing or invalid or a migration fails.

## Check a deployed stack

Start a disposable Compose project, run the black-box smoke check against it, then remove it:

```sh
FRONTEND_PORT=15185 docker compose --project-name stackplan-smoke up --build --detach --wait app
STACKPLAN_DEPLOYMENT_URL=http://127.0.0.1:15185 python tests/deployment/smoke.py
docker compose --project-name stackplan-smoke down --volumes
```

The check covers health and readiness, both pages, and creating a project and reading it back through PostgreSQL. It prints one line per check, needs no provider credentials, and exits with status 1 if any check fails. Without `STACKPLAN_DEPLOYMENT_URL` it targets `http://127.0.0.1:5173`, the default Compose port.

## Preview processing states

Run the isolated loading-state preview from the repository root:

```sh
npm run demo:loading --prefix frontend
```

Open the printed local URL and change the `project` query parameter to `queued`, `parsing`, `extracting`, `validating`, `success`, `failed`, `interrupted`, or `offline` to inspect each state. The preview serves the real frontend with fixture API responses; it does not start the backend, access a database, upload files, or call an AI provider. It binds to loopback port 5175 by default; set `PORT` to use another port.

## Working with the models

The package exposes related model types from their subpackages. For example:

```python
from src.models.assessments import AssessmentCollection, Schedule
from src.models.processing import DocumentOutcome, ProcessingJob
```

Use the tests as executable examples of construction, validation, immutability, and schedule-building behaviour.
