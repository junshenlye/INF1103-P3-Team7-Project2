"""Run the background document-processing worker."""

import asyncio
import signal

import httpx

from src.config.settings import load_settings
from src.managers.ai_manager import AIManager
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.storage.postgres_pool import open_postgres_pool


async def run(settings=None):
    """Poll PostgreSQL for work until the process receives a shutdown signal."""
    settings = settings or load_settings()

    with open_postgres_pool(settings) as pool:
        data = DataManager(pool)
        async with (
            httpx.AsyncClient(
                base_url=settings.docling_url,
                timeout=settings.provider_timeout,
                trust_env=False,
            ) as docling,
            httpx.AsyncClient(
                base_url=settings.gpt_base_url,
                timeout=settings.provider_timeout,
                trust_env=False,
            ) as gpt,
        ):
            manager = AIManager(data, LogicManager(), docling, gpt, settings)
            task = asyncio.current_task()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, task.cancel)

            while True:
                if not await manager.process_next_job():
                    await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
