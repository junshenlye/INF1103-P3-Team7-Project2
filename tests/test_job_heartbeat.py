"""Tests for renewing a processing job's lease while it runs."""

import asyncio
import unittest

from src.config import limits
from src.processing.job_heartbeat import heartbeat_interval, job_heartbeat


class HeartbeatStore:
    def __init__(self, fail_after=None):
        self.beats = []
        self.fail_after = fail_after

    def save_job_heartbeat(self, job, stage=None):
        if self.fail_after is not None and len(self.beats) >= self.fail_after:
            raise ConnectionError("lease lost")
        self.beats.append(job)


class HeartbeatIntervalTests(unittest.TestCase):
    def test_renews_three_times_per_lease_up_to_the_cap(self):
        self.assertEqual(heartbeat_interval(9), 3)
        self.assertEqual(heartbeat_interval(limits.LEASE_SECONDS), limits.MAX_HEARTBEAT_INTERVAL)
        self.assertEqual(heartbeat_interval(3 * limits.MAX_HEARTBEAT_INTERVAL + 30), limits.MAX_HEARTBEAT_INTERVAL)

    def test_rejects_non_positive_leases(self):
        for lease in (0, -5):
            with self.subTest(lease=lease):
                with self.assertRaises(ValueError):
                    heartbeat_interval(lease)


class JobHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_renews_the_lease_while_the_block_runs(self):
        store = HeartbeatStore()
        async with job_heartbeat(store, "job-1", 60, interval=0.01):
            await asyncio.sleep(0.08)
        self.assertGreaterEqual(len(store.beats), 2)
        self.assertEqual(set(store.beats), {"job-1"})

    async def test_stops_renewing_after_the_block_exits(self):
        store = HeartbeatStore()
        async with job_heartbeat(store, "job-1", 60, interval=0.01):
            await asyncio.sleep(0.03)
        count = len(store.beats)
        await asyncio.sleep(0.05)
        self.assertEqual(len(store.beats), count)

    async def test_stops_renewing_when_the_block_raises(self):
        store = HeartbeatStore()
        with self.assertRaises(RuntimeError):
            async with job_heartbeat(store, "job-1", 60, interval=0.01):
                raise RuntimeError("processing failed")
        await asyncio.sleep(0.03)
        self.assertEqual(store.beats, [])

    async def test_failed_renewal_cancels_the_owning_task(self):
        store = HeartbeatStore(fail_after=1)
        reached_end = False

        async def work():
            nonlocal reached_end
            async with job_heartbeat(store, "job-1", 60, interval=0.01):
                await asyncio.sleep(5)
                reached_end = True

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.create_task(work()), 2)
        self.assertFalse(reached_end)
        self.assertEqual(store.beats, ["job-1"])

    async def test_rejects_a_non_positive_interval(self):
        with self.assertRaises(ValueError):
            async with job_heartbeat(HeartbeatStore(), "job-1", 60, interval=0):
                pass


if __name__ == "__main__":
    unittest.main()
