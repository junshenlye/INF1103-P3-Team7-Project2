# Document processing recovery

This guide describes how the current worker preserves progress and recovers a submission after provider errors or worker interruption. It is based on the implementation in `src/processing/`, `src/storage/`, and the processing tests.

## What is persisted

Document processing is split into durable work and immutable checkpoints:

- A parsed document is saved as a checkpoint with its source elements and chunk size.
- Each accepted extraction chunk is saved separately.
- A retry reuses the saved parse and skips chunks already accepted for that parse.
- Provider attempts are recorded with a safe error code/message, stage, attempt number, and available HTTP status details.

This means a later failure does not require already accepted chunks to be extracted again. A provider call that succeeds remotely but fails before its result is committed can still be repeated; the system does not promise exactly-once provider execution.

## Provider failures

Parsing and extraction steps use the shared retry policy in `src/processing/attempts.py`.

- Transient provider failures are retried within the configured attempt and delay bounds. A bounded `Retry-After` value is considered when supplied.
- An invalid extraction can receive a corrective retry with the previous safe validation feedback.
- Every failed attempt is recorded before retrying or returning the final error.
- Cancellation and an explicit processing-interrupted error stop immediately rather than starting another attempt.
- A chunk that exhausts its retry policy is recorded as an issue; processing can continue with other chunks. A parse failure or interruption is raised to the caller to settle the document task.

Provider calls run under shared provider permits and a timeout. The permit limits apply across worker processes, rather than only within one Python process.

## Worker interruption and lease recovery

A worker renews its claimed job lease in the background. If renewal fails, the active processing task is cancelled so it cannot continue writing under a lease that another worker may have reclaimed.

The PostgreSQL recovery adapter periodically finds running jobs whose lease has expired. In one transaction it:

1. Locks eligible jobs with `FOR UPDATE SKIP LOCKED`, so concurrent recovery workers do not recover the same job.
2. Returns unfinished running document tasks to the queued state and clears their ownership token.
3. Resets affected document progress from parsing or extracting to waiting.
4. Requeues the job while its recovery count is below the configured maximum.
5. After the recovery limit is exhausted, marks unfinished documents stopped, records a processing-interrupted issue, and settles the job as interrupted.

The current default recovery limit is three. Completed document work and saved checkpoints are retained; only unfinished tasks are made eligible for another attempt.

## Reading the resulting state

Execution state and inference outcome are separate. A task may finish executing while its source remains partially understood or contains no assessment information. Do not interpret a completed task as proof that every assessment fact was found.

A partial schedule can contain validated facts while other sources or chunks remain unresolved. Unknown weeks and weights remain unknown rather than being guessed. When a document is replaced or a newer revision is published, use the API's stale/current indicators rather than assuming an older schedule reflects the latest inputs.

For the full data flow and manager responsibilities, see [Architecture](../ARCHITECTURE.md). The tests under `tests/test_*` exercise checkpoint reuse, retry handling, worker leases, recovery, and lifecycle transitions.

## Operational limitations

- A provider request may have completed remotely just before a process or network failure. If its result was not committed, a retry may incur another provider call.
- Automatic recovery is bounded. After the configured recovery budget is exhausted, unfinished work requires an explicit retry or other user action.
- Automated tests use controlled provider and persistence doubles for most processing paths; they do not establish extraction accuracy for arbitrary real-world documents.
