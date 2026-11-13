"""Limit how many provider calls run at once across every worker."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

POLL_SECONDS = 0.05


@asynccontextmanager
async def provider_permit(data, job, provider: str, capacity: int, poll_seconds: float = POLL_SECONDS):
    """Hold one of ``capacity`` shared slots for ``provider`` while the block runs.

    ``data`` provides ``acquire_provider_permit`` and ``release_provider_permit``
    from the worker data contract. Storage calls run in a thread so the event
    loop keeps serving other documents. While every slot is busy the permit
    is requested again after ``poll_seconds``. The slot is always released,
    including when the block raises or is cancelled.
    """
    if capacity < 1:
        raise ValueError("Provider capacity must be at least one.")
    if poll_seconds < 0:
        raise ValueError("The permit poll interval cannot be negative.")
    slot = None
    while slot is None:
        slot = await asyncio.to_thread(data.acquire_provider_permit, job, provider, capacity)
        if slot is None:
            await asyncio.sleep(poll_seconds)
    try:
        yield slot
    finally:
        await asyncio.to_thread(data.release_provider_permit, job, provider, slot)
