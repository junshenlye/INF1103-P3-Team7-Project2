"""Tests for sharing a bounded number of provider slots between workers."""

import asyncio
import threading
import unittest

from src.processing.provider_permit import provider_permit


class PermitStore:
    """In-memory stand-in for the permit operations of the worker data contract."""

    def __init__(self, busy_polls=0):
        self.busy_polls = busy_polls
        self.held = {}
        self.calls = []
        self.lock = threading.Lock()

    def acquire_provider_permit(self, job, provider, capacity):
        with self.lock:
            self.calls.append(("acquire", job, provider, capacity))
            if self.busy_polls:
                self.busy_polls -= 1
                return None
            used = self.held.setdefault(provider, set())
            free = [slot for slot in range(capacity) if slot not in used]
            if not free:
                return None
            used.add(free[0])
            return free[0]

    def release_provider_permit(self, job, provider, slot):
        with self.lock:
            self.calls.append(("release", job, provider, slot))
            self.held[provider].remove(slot)


class ProviderPermitTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_a_slot_and_releases_it(self):
        store = PermitStore()
        async with provider_permit(store, "job-1", "gpt", 2) as slot:
            self.assertEqual(slot, 0)
            self.assertEqual(store.held["gpt"], {0})
        self.assertEqual(store.held["gpt"], set())
        self.assertEqual(
            store.calls,
            [("acquire", "job-1", "gpt", 2), ("release", "job-1", "gpt", 0)],
        )

    async def test_waits_while_every_slot_is_busy(self):
        store = PermitStore(busy_polls=2)
        async with provider_permit(store, "job-1", "docling", 1, poll_seconds=0) as slot:
            self.assertEqual(slot, 0)
        self.assertEqual([call[0] for call in store.calls], ["acquire"] * 3 + ["release"])

    async def test_never_exceeds_capacity(self):
        store = PermitStore()
        active = peak = 0

        async def call():
            nonlocal active, peak
            async with provider_permit(store, "job-1", "gpt", 2, poll_seconds=0):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(call() for _ in range(6)))
        self.assertEqual(peak, 2)
        self.assertEqual(store.held["gpt"], set())

    async def test_releases_when_the_block_fails_or_is_cancelled(self):
        store = PermitStore()
        with self.assertRaises(RuntimeError):
            async with provider_permit(store, "job-1", "gpt", 1):
                raise RuntimeError("provider failed")
        self.assertEqual(store.held["gpt"], set())

        entered = asyncio.Event()

        async def held_forever():
            async with provider_permit(store, "job-1", "gpt", 1):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(held_forever())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(store.held["gpt"], set())

    async def test_rejects_invalid_arguments(self):
        for capacity, poll in ((0, 0.05), (1, -1)):
            with self.subTest(capacity=capacity, poll=poll):
                with self.assertRaises(ValueError):
                    async with provider_permit(PermitStore(), "job-1", "gpt", capacity, poll):
                        pass


if __name__ == "__main__":
    unittest.main()
