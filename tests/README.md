# Testing guide

The checks below are the same ones the CI workflow (`.github/workflows/tests.yml`) runs on every push and pull request. Run every command from the repository root unless a step says otherwise.

## One-time setup

| Need | Command |
| --- | --- |
| Python 3.12 and development tools | `python -m pip install -r requirements-dev.txt` |
| Node 22 frontend dependencies | `npm ci --prefix frontend` |
| Chromium for browser tests | `cd frontend && npx playwright install chromium` |

Without `requirements.txt` installed, the HTTP endpoint tests skip themselves (they need FastAPI and httpx), and the worker entry-point test fails because it needs httpx.

## Everything at once

```sh
python scripts/test.py
```

It runs the steps below in order and stops at the first failure: compile, Ruff, Python and notifier unit tests, frontend checks, and all three browser regressions.

## Individual checks

| What | Command | Notes |
| --- | --- | --- |
| Compile | `python -m compileall -q src tests integrations/github_actions_notifier and integrations/telegram_bot` | Catches syntax errors in every Python module. |
| Lint | `ruff check src tests integrations/github_actions_notifier and integrations/telegram_bot` | Rules come from `pyproject.toml`. |
| Python unit tests | `python -m unittest discover -s tests -v` | No database or network needed. |
| Telegram notifier tests | `python -m unittest discover -s integrations/github_actions_notifier and integrations/telegram_bot -v` | Mocks GitHub and Telegram; never sends messages. |
| Frontend checks | `npm run check --prefix frontend` | Syntax-checks the scripts, then runs `tests/frontend/*.test.mjs` with `node --test`. |
| Loading browser regression | `npm run test:loading --prefix frontend` | Processing and loading screens in headless Chromium. |
| Calendar browser regression | `npm run test:calendar --prefix frontend` | Calendar and list views, filters and mobile layout, using fixture API responses. |
| Submission recovery browser regression | `npm run test:recovery --prefix frontend` | Recovers a saved project after a temporary status-poll failure and ensures no duplicate submission is sent. |

The browser regressions serve the frontend from a local server on an unused loopback port and never contact the real application or a database. To use an existing Chrome or Chromium instead of the Playwright download, set `BROWSER_EXECUTABLE` to its executable path.

## Python tests in Docker

The `test` profile in `compose.yaml` builds the `test` stage of the `Dockerfile` and runs `pytest` against the suite, next to a throwaway PostgreSQL service:

```sh
docker compose --project-name stackplan-tests --profile test run --build --rm tests
docker compose --project-name stackplan-tests --profile test down --volumes
```

Use a dedicated project name so the run never touches the containers or volumes of a normal local stack, and remove it with `down --volumes` afterwards.

## Where tests live

- `tests/test_*.py`: Python unit tests using the standard-library `unittest` runner (`pytest` also collects them, as configured in `pytest.ini`).
- `integrations/github_actions_notifier and integrations/telegram_bot/test_watch.py`: isolated notifier tests with mocked remote services.
- `tests/frontend/*.test.mjs`: frontend unit tests run by `node --test`.
- `tests/frontend/loading.mjs`, `tests/frontend/calendar.mjs`, `tests/frontend/recovery.mjs`: Playwright browser regressions.

New Python test files must be named `test_*.py` to be discovered. New frontend unit tests must end in `.test.mjs`.

## Known local differences

- **Windows:** the settings tests that use the default `DOCUMENT_DIRECTORY` (`/data/documents`) fail, because that path is not absolute on Windows. They pass on Linux, in CI and in the Docker test run.
- **Missing Chromium:** the browser regressions fail to launch until Chromium is installed or `BROWSER_EXECUTABLE` is set.
