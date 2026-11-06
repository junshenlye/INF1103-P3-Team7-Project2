# Document pipeline prototype

Standalone prototype retained for review during the Feature #1 rewrite.
The old benchmark runners, fixtures, acceptance gates and validation reports
have been removed. This is separate from the production application.

## Try the document interface

Run the standalone interface without changing the existing app:

```sh
python -m experiments.document_pipeline.demo --data-dir /tmp/stackplan-document-workspace
```

Open `http://127.0.0.1:18766`. Add a module and its documents. The original
PDF/image stays in the centre, with assessment metadata on the right. Selecting
a date, weight or instruction highlights its supporting region. Multi-page
references offer page buttons. Results survive refreshes; `--data-dir` retains
originals and completed results across restarts. Without it, files are temporary.
Interrupted work is reported as interrupted on restart, not as completed.

The same isolated interface can be run with Docker:

```sh
docker compose --env-file .env -p stackplan-document-trial -f experiments/document_pipeline/compose.yaml --profile demo up --build -d
```

Its document volume is separate from the existing StackPlan database. It uses
one Gunicorn worker with a bounded background queue; do not increase the worker
count while the job coordinator is process-local. The parser and app ports are
bound to localhost. The UI reports real stages, never an invented percentage.
The trial is a review workspace, not a production replacement or a study-plan
interface. No generated study tasks are presented as source facts.
