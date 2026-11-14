"""Tests for the background worker entry point."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

from src.worker import run


class WorkerEntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_wires_clients_and_waits_when_no_job_is_available(self):
        settings = SimpleNamespace(
            docling_url="http://docling:5001",
            gpt_base_url="https://api.example.test/v1",
            provider_timeout=30,
        )
        pool = object()
        docling = MagicMock()
        docling.__aenter__ = AsyncMock(return_value=docling)
        docling.__aexit__ = AsyncMock(return_value=None)
        gpt = MagicMock()
        gpt.__aenter__ = AsyncMock(return_value=gpt)
        gpt.__aexit__ = AsyncMock(return_value=None)
        manager = MagicMock()
        manager.process_next_job = AsyncMock(return_value=False)

        with (
            patch("src.worker.open_postgres_pool", return_value=nullcontext(pool)),
            patch("src.worker.DataManager") as data_manager,
            patch("src.worker.httpx.AsyncClient", side_effect=[docling, gpt]) as client,
            patch("src.worker.AIManager", return_value=manager) as ai_manager,
            patch(
                "src.worker.asyncio.sleep",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ) as sleep,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await run(settings)

        data_manager.assert_called_once_with(pool)
        self.assertEqual(
            client.call_args_list,
            [
                call(
                    base_url=settings.docling_url,
                    timeout=settings.provider_timeout,
                    trust_env=False,
                ),
                call(
                    base_url=settings.gpt_base_url,
                    timeout=settings.provider_timeout,
                    trust_env=False,
                ),
            ],
        )
        ai_manager.assert_called_once()
        self.assertIs(ai_manager.call_args.args[0], data_manager.return_value)
        self.assertIs(ai_manager.call_args.args[2], docling)
        self.assertIs(ai_manager.call_args.args[3], gpt)
        manager.process_next_job.assert_awaited_once_with()
        sleep.assert_awaited_once_with(1)
        docling.__aexit__.assert_awaited_once()
        gpt.__aexit__.assert_awaited_once()
