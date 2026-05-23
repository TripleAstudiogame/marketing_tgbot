from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot

from app.db import async_session_factory
from app.services.jobs import get_next_pending_job, recover_stale_jobs
from app.services.report_pipeline import ReportPipeline

logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_job_id: int | None = None
    processed_jobs: int = 0
    failed_iterations: int = 0
    last_error: str = ""
    running: bool = False


worker_state = WorkerState()


async def process_one_job(bot: Bot) -> bool:
    async with async_session_factory() as session:
        job = await get_next_pending_job(session)
        if not job:
            return False
        worker_state.last_job_id = job.id
        logger.info("Processing job %s", job.id)
        pipeline = ReportPipeline(bot)
        await pipeline.run(session, job)
        worker_state.processed_jobs += 1
        logger.info("Finished job %s", job.id)
        return True


async def worker_loop(
    bot: Bot,
    stop_condition: Callable[[], bool] | None = None,
    sleep_seconds: float = 2.5,
) -> None:
    worker_state.started_at = datetime.now(timezone.utc)
    worker_state.running = True
    logger.info("Worker loop started")
    async with async_session_factory() as session:
        recovered = await recover_stale_jobs(session)
        if recovered:
            logger.warning("Recovered %s stale running job(s)", recovered)
    while True:
        if stop_condition and stop_condition():
            worker_state.running = False
            logger.info("Worker loop stopped by stop condition")
            return
        worked = False
        worker_state.last_heartbeat_at = datetime.now(timezone.utc)
        try:
            worked = await process_one_job(bot)
            worker_state.last_error = ""
        except asyncio.CancelledError:
            worker_state.running = False
            logger.info("Worker loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            worker_state.failed_iterations += 1
            worker_state.last_error = str(exc)
            logger.exception("Worker iteration failed")
            await asyncio.sleep(min(30, sleep_seconds * 4))
        if not worked:
            await asyncio.sleep(sleep_seconds)
