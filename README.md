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

## Run the tests

The test suite uses Python's standard-library `unittest` runner:

```sh
python -m unittest discover -s tests -v
```

Run the command from the repository root. A successful run reports each test and ends with an `OK` summary.

## Working with the models

The package exposes related model types from their subpackages. For example:

```python
from src.models.assessments import AssessmentCollection, Schedule
from src.models.processing import DocumentOutcome, ProcessingJob
```

Use the tests as executable examples of construction, validation, immutability, and schedule-building behaviour.
