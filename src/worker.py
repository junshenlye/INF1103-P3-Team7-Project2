import asyncio
from datetime import datetime, timedelta, timezone
import signal

import httpx

from src.config import limits
from src.managers.ai_manager import AIManager
from src.managers.data_manager import DataManager
from src.managers.logic_manager import LogicManager
from src.config.settings import load_settings


async def run(settings=None):
    settings = settings or load_settings()
    logic = LogicManager()
    with DataManager.create_pool(settings.database_url, settings.pool_size) as pool:
        data = DataManager(
            pool,
            settings.document_directory,
            settings.document_bytes,
            settings.lease_seconds,
            logic_manager=logic,
        )
        await asyncio.to_thread(
            data.cleanup_orphaned_files,
            datetime.now(timezone.utc) - timedelta(seconds=limits.CLEANUP_AGE_SECONDS),
        )
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
            ai = AIManager(data, logic, docling, gpt, settings)
            task = asyncio.current_task()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, task.cancel)
            last_cleanup = loop.time()
            while True:
                if not await ai.process_next_job():
                    await asyncio.sleep(1)
                if loop.time() - last_cleanup > limits.CLEANUP_INTERVAL_SECONDS:
                    await asyncio.to_thread(
                        data.cleanup_orphaned_files,
                        datetime.now(timezone.utc)
                        - timedelta(seconds=limits.CLEANUP_AGE_SECONDS),
                    )
                    last_cleanup = loop.time()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
