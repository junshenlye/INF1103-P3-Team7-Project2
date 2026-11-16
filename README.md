# Stackplan

Stackplan turns module briefs, PDFs and images into an assessment calendar with traceable source evidence. AI extracts the facts; deterministic rules validate assessment relationships, weights and timing before publication. Unknown facts remain unknown, and a failed document does not discard successful results.

Built for INF1103 Project Part 2 using Python, FastAPI, PostgreSQL, Docling and a browser interface.

## Features

- Submit several modules and their PDF, PNG or JPEG documents together.
- View assessments by week, including ranges and assessments with unknown timing.
- Inspect the original document, extracted text and supporting source highlights.
- Retry a failed document or replace an original while retaining successful work and historical evidence.
- Apply evidence-backed corrections through the review API, with append-only revisions and correction lineage.
- Resume interrupted work using durable checkpoints, fenced worker claims and idempotent requests.

## Run with Docker

Install Docker with Compose. Copy `.env.example` to `.env` if you do not already have a configuration file, then set:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model
```

The configured model must support the strict JSON Schema response format used by the extraction request. `GPT_API_KEY` and `GPT_MODEL` can override the corresponding OpenAI settings. Keep credentials in the ignored `.env` file.

From the repository root:

```sh
docker compose up --build --detach
```

Open **http://127.0.0.1:5173**. Compose starts PostgreSQL, applies migrations, starts the web application and worker, and starts Docling. Docling's first startup can take several minutes.

The launchers `scripts/start.sh` and `scripts/start.ps1` run the same Docker command. To use an existing Docling service, set `DOCLING_URL` and start `docker compose up --build --detach app worker`.

```sh
# Stop the application; named data volumes are retained.
docker compose down
```

Rebuild after changing source files. Both the app and worker use the same database and original-document volume.

### Configuration

| Variable | Purpose / default |
| --- | --- |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Extraction credentials and model; required for live processing. |
| `GPT_API_KEY`, `GPT_MODEL` | Optional overrides for extraction credentials/model. |
| `GPT_BASE_URL` | Extraction API base URL; defaults to `https://api.openai.com/v1`. |
| `DOCLING_URL` | OCR/document conversion service; defaults to `http://docling:5001`. |
| `FRONTEND_PORT` | Local web port; defaults to `5173`. |
| `DOCUMENT_WORKERS` | Concurrent document consumers; defaults to `3`. |
| `GPT_CONCURRENCY` | Maximum concurrent GPT calls across worker processes; defaults to `2`. |
| `POSTGRES_PASSWORD` | Local database password; see `.env.example`. |

The app exposes authoritative upload/form bounds at `GET /api/limits`. Defaults are 50 MiB per request, 10 MiB per document, 20 modules and 10 documents per module.

## Use the application

1. Name a trimester and add modules with their source documents to the browser's submission bucket.
2. Review the documents, then build the assessment schedule.
3. Follow processing progress. Validated results can appear while other documents are still being processed.
4. Select an assessment to inspect its cited source text and original. Highlights are shown when valid page coordinates are available.
5. For unresolved documents, retry the failed work or supply a clearer replacement.

Project status follows `Created → Processing → Ready | Partial | Failed | Interrupted`. Execution status, understanding, coverage and stale results are tracked separately. Retries reuse saved parses and accepted chunks. Replacements receive a new document identity; original evidence and older results remain available.

## Architecture

The application has **17 classes**: four managers, nine domain classes and four supporting classes. Only managers coordinate application objects. Entities operate on their own state and never call another entity or a manager.

| Manager | Responsibility |
| --- | --- |
| `IOManager` | HTTP input/output, upload handling, source delivery, responses and progress streaming. |
| `AIManager` | Background document processing, parsing/chunking, provider requests and bounded retries. |
| `LogicManager` | Input/fact/evidence validation, assessment construction, scheduling, reconciliation and lifecycle decisions. No network or storage work. |
| `DataManager` | SQL, original files, staging, claims/leases, checkpoints, publication, snapshots and history. |

IOManager validates input through LogicManager and accepts work through DataManager. AIManager independently claims queued work through the WorkerData interface. IOManager, AIManager and DataManager request pure business decisions from LogicManager; LogicManager does not call back into them. Provider calls run outside database transactions.

### UML class diagram

Each box shows selected attributes and operations. `+` is public; `-` is internal. Italics indicate abstract operations and underlining indicates static operations. Parameters are abbreviated where needed.

Arrows point from a manager to the collaborator it uses. Hollow triangles point to a superclass/interface. Diamonds describe passive grouping or ownership; they do not represent entity-to-entity calls. Module aggregates independently created assessments; Document exclusively owns its source elements. External library types are not additional application classes.

```mermaid
---
title: Stackplan — implemented UML class diagram
config:
  theme: neutral
  class:
    hideEmptyMembersBox: true
    nodeSpacing: 25
    rankSpacing: 45
---
classDiagram
    direction TB

    namespace Control_Plane {
    class IOManager {
        <<manager>>
        -DataManager _data
        -LogicManager _logic
        +handle_submit_bucket(request)
        +get_project(project_id) dict
        +handle_assessment_review(request)
        +get_project_events(...)
    }
    class DataManager {
        <<manager>>
        -ConnectionPool _pool
        -LogicManager _logic
        -dict _staging
        +create_project(name, week_count) Project
        +create_processing_job(...) ProcessingJob
        +save_parse_snapshot(...)
        +save_extraction_result(...)
        +get_project_snapshot(project_id) dict
        +save_review_revision(...) int
    }
    class AIManager {
        <<manager>>
        -WorkerData _data
        -LogicManager _logic
        -ProviderClient _docling
        -ProviderClient _gpt
        -Settings _settings
        +process_next_job() bool
        -_read_source_elements(parsed) list
        -_make_chunks(elements) list
        -_call_docling(stream, document) dict
        -_call_gpt(...) dict
        -_retry_provider(...)
    }
    class LogicManager {
        <<manager>>
        +validate_submission(...) tuple
        +validate_extraction(...) tuple
        +create_assessment(...) Assessment$
        +build_schedule(...) Schedule
        +build_document_outcome(...) dict$
        +reconcile_reviews(...) tuple
        +can_retry_document(...) bool$
    }
    }
    namespace Domain_Model {
    class Project {
        +str id
        +str name
        +int week_count
        +str status
    }
    class Module {
        +str id
        +str module_title
        +int credit
        -tuple~Assessment~ _assessments
        +get_assessments() tuple~Assessment~
    }
    class Document {
        +str id
        +str filename
        +str checksum
        -str _storage_key
        -tuple~SourceElement~ _sources
        +get_sources() tuple~SourceElement~
    }
    class SourceElement {
        +str id
        +str parse_id
        +str text
        -list _regions
        +to_record() dict
    }
    class ProcessingJob {
        +str id
        +str project_id
        +str status
        +str stage
        +str lease_token
    }
    class Assessment {
        <<abstract>>
        +str id
        +str module_id
        -dict _facts
        -dict _evidence
        +scheduling_span() Optional~tuple~*
        +to_record(module_title) dict
    }
    class IndividualAssessment {
        +scheduling_span() Optional~tuple~
    }
    class AssessmentGroup {
        +scheduling_span() Optional~tuple~
    }
    class Schedule {
        +int week_count
        -dict _weeks
        -list _undated
        +add_item(record, start, end)
        +add_undated(record)
        +to_record() dict
    }
    }
    class WorkerData {
        <<interface>>
        +claim_next_job() ProcessingJob*
        +get_document_checkpoint(document_id) dict*
        +save_extraction_result(...)*
        +complete_job(job)*
    }
    class ProviderClient {
        <<interface>>
        +stream(...) AsyncContextManager
    }
    class Settings {
        +int chunk_bytes
        +int max_chunks
        +float provider_timeout
        +validate()
    }
    class ProcessingError {
        <<exception>>
        +str code
        +str message
        +str scope
        +to_issue() dict
    }

    IOManager --> DataManager : persistence
    IOManager --> LogicManager : input checks
    DataManager --> LogicManager : lifecycle checks
    AIManager --> LogicManager : AI fact checks
    AIManager --> WorkerData : checkpoints
    AIManager --> ProviderClient : API calls
    AIManager --> Settings : reads config
    DataManager ..|> WorkerData : implements
    IOManager ..> ProcessingError : maps errors

    DataManager ..> Project : creates / loads
    DataManager ..> Module : creates / loads
    DataManager ..> Document : loads with sources
    DataManager ..> ProcessingJob : creates / claims
    LogicManager ..> Module : reads references
    LogicManager ..> Assessment : factory / queries
    LogicManager ..> Schedule : builds

    Assessment <|-- IndividualAssessment
    Assessment <|-- AssessmentGroup
    Module "1" o-- "0..*" Assessment : passive references
    Document "1" *-- "0..*" SourceElement : owns sources
```

### Source layout

```text
src/
  managers/
    io_manager.py              IOManager
    logic_manager.py           LogicManager
    ai_manager.py              AIManager
    data_manager.py            DataManager
  models/
    projects/
      project.py               Project
      module.py                Module
    documents/
      document.py              Document
      source_element.py        SourceElement
    processing/
      processing_job.py        ProcessingJob
      lifecycle.py             State/stage constants
    assessments/
      assessment.py            Assessment (abstract)
      individual_assessment.py IndividualAssessment
      assessment_group.py      AssessmentGroup
      schedule.py              Schedule
  contracts/
    worker_data.py             WorkerData (ABC implemented by DataManager)
    provider_client.py         ProviderClient (transport Protocol)
  config/
    settings.py                Settings
    limits.py                  Application bounds
  errors/
    processing_error.py        ProcessingError
    error_codes.py             Issue-code vocabulary
    issues.py                  Primitive issue projections
  serialization/
    json_data.py               Strict JSON decoding
  main.py                      Web composition root
  worker.py                    Worker composition root
  migrate.py                   Migration/repair entry point
database/migrations/           Versioned PostgreSQL schema and constraints
frontend/                      Browser pages, styles and API clients
scripts/                       Launchers, verification runner and UML checker
tests/                         Unit, storage, API, recovery, browser and deployment checks
```

Temporary submission, staging, checkpoint and response values are dictionaries owned by their managers. They are not additional application classes. The two classes outside `src/` are test helpers: a fake provider HTTP handler and an entity-isolation probe.

### OOP and SOL principles

- **Encapsulation:** mutable assessment facts, evidence and source geometry are copied at boundaries. Domain identity equality does not inspect peers; passive references are excluded from generated representations.
- **Abstraction, inheritance and polymorphism:** Assessment defines `scheduling_span()`. IndividualAssessment returns its own range/unknown timing; AssessmentGroup excludes its aggregate total. LogicManager uses the same query without subtype-specific scheduling branches.
- **Interfaces:** DataManager explicitly implements the WorkerData ABC; external HTTP clients satisfy ProviderClient.
- **Association, aggregation and composition:** injected manager collaborators; Module–Assessment grouping; exclusive Document–SourceElement ownership validated by DataManager.
- **SRP:** managers separate HTTP, provider processing, business decisions and persistence.
- **OCP:** a new valid assessment subtype can answer the shared query without changing the scheduling loop; factory/input registration may still change.
- **LSP:** both assessment subtypes obey the same span/undated/excluded contract without changing saved facts or requiring different client preconditions.

## API and persistence

The same app serves the browser and API. Endpoint schemas are available at `/openapi.json`.

| Endpoint | Purpose |
| --- | --- |
| `GET /health`, `GET /ready` | Application/database readiness. |
| `POST /api/projects` | Create a project. |
| `POST /api/projects/{id}/process` | Accept a multipart module/document submission with an Idempotency-Key. |
| `GET /api/projects/{id}`, `GET /api/jobs/{id}` | Read committed schedule, coverage and processing state. |
| `GET /api/projects/{id}/events` | Durable progress stream with Last-Event-ID replay. |
| `GET /api/results/{id}` | Inspect a published result and its effective assessment facts. |
| `GET /api/documents/{id}/original`, `GET /api/documents/{id}/trace` | Retrieve original bytes and saved evidence. |
| `POST /api/documents/{id}/retry` | Retry using `expected_generation` and an Idempotency-Key. |
| `POST /api/documents/{id}/replacement` | Replace using raw bytes, X-Filename, Expected-Generation and Idempotency-Key headers. |
| `POST /api/results/{result_id}/assessments/{assessment_id}/reviews` | Append an evidence-backed correction with `expected_revision`. |

PostgreSQL stores immutable parses, accepted chunks, assessment results, reviews, current result heads and progress events. Original files are checksummed and stored separately under DataManager. Seven migrations run before the web app and worker start.

A retry increments its document generation once per request key. Lease recovery obtains a new worker token; stale workers cannot write. Successful siblings remain published. Review/publication conflicts re-read current versions, while replaced evidence can mark a reviewed result stale rather than silently overwrite it. Project responses use one consistent snapshot and event cursor.

## Testing

Tests use deterministic Docling/GPT responses and do not require paid API access.

### Backend checks inside Docker

```sh
docker compose --project-name stackplan-oop-check --profile test run --build --rm tests
docker compose --project-name stackplan-oop-check --profile test down --volumes
```

This uses a separate disposable test database. The host-assisted backup/restore test is covered by the full runner below.

### Full verification

Requires Docker, Python 3.9+, Node.js 20+ and Playwright Chromium. Docker and CI use Python 3.12.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci --prefix frontend
cd frontend
npx playwright install chromium
cd ..
.venv/bin/python scripts/check_uml.py
.venv/bin/python scripts/test.py
```

On Windows, use `.venv\Scripts\python.exe` instead of `.venv/bin/python`. `BROWSER_EXECUTABLE` can select an installed Chrome browser; `PLAYWRIGHT_MODULE` can select an existing Playwright module.

The runner creates a uniquely named PostgreSQL container and temporary document storage, runs Python/JavaScript/browser checks, then cleans up its own services. It covers schema validation, content/size limits, ownership, schedules, partial publication, retries/replacements, cancellation, stale leases, concurrent reviews, consistent snapshots, original-file recovery and backup/restore.

To retain the synthetic state-transition trace, set `STACKPLAN_TEST_ARTIFACT_DIR=test-results` before running the suite. The trace records actual API/SQL snapshots for `Created → Processing → Partial → Processing → Ready`, including a targeted generation-2 retry with parse reuse. Test artifacts are ignored by Git.

Latest local verification (15 November 2026): **166 Python tests, 8 frontend tests, 10 browser scenarios and 7 Docker startup checks passed**. The standalone Docker test image passed 165 tests; its one host-assisted restore check passed in the full host run.

GitHub Actions checks README's UML against source and runs the isolated suite on pushes and pull requests. Without a configured disposable test database, direct pytest runs skip database tests; use the documented runner for complete verification.

## Operational notes

Closing the browser does not stop an accepted job. Unexpected worker death requeues unfinished work with a fresh fenced lease, up to three recoveries. Provider retries are bounded: invalid extraction receives one corrective retry; transient service failures receive up to three calls. Missing originals retain saved facts/evidence with a scoped warning. The application is intended for local single-user use, and live extraction accuracy depends on the supplied documents and configured providers.
