"""Keep a claimed processing job's lease alive while it is being worked on."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from src.config import limits


def heartbeat_interval(lease_seconds: float) -> float:
    """Return how often to renew a lease: a third of it, capped by the shared limit.

    Renewing three times per lease tolerates a slow or missed heartbeat
    before the lease expires and another worker treats the job as abandoned.
    """
    if lease_seconds <= 0:
        raise ValueError("The lease must be positive.")
    return min(lease_seconds / 3, limits.MAX_HEARTBEAT_INTERVAL)


@asynccontextmanager
async def job_heartbeat(data, job, lease_seconds: float, interval: float | None = None):
    """Renew ``job``'s lease in the background while the block runs.

    ``data.save_job_heartbeat(job)`` is called every ``interval`` seconds
    (``heartbeat_interval(lease_seconds)`` by default) in a worker thread.
    If a renewal fails, the lease can no longer be trusted, so the task that
    entered the block is cancelled instead of continuing to write results
    for a job another worker may have reclaimed. The background renewal
    always stops when the block exits.
    """
    every = heartbeat_interval(lease_seconds) if interval is None else interval
    if every <= 0:
        raise ValueError("The heartbeat interval must be positive.")
    owner = asyncio.current_task()

    async def renew():
        while True:
            await asyncio.sleep(every)
            try:
                await asyncio.to_thread(data.save_job_heartbeat, job)
            except Exception:
                owner.cancel()
                return

    monitor = asyncio.create_task(renew())
    try:
        yield
    finally:
        monitor.cancel()
        with suppress(asyncio.CancelledError):
            await monitor
