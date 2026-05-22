from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from aiogram import Bot

from app.db import async_session_factory
from app.models import JobStatus
from app.services.jobs import get_next_pending_job
from app.services.report_pipeline import ReportPipeline


async def process_one_job(bot: Bot) -> bool:
    async with async_session_factory() as session:
        job = await get_next_pending_job(session)
        if not job:
            return False
        if job.status == JobStatus.canceled:
            return True
        pipeline = ReportPipeline(bot)
        await pipeline.run(session, job)
        return True


async def worker_loop(
    bot: Bot,
    stop_condition: Callable[[], bool] | None = None,
    sleep_seconds: float = 2.5,
) -> None:
    while True:
        if stop_condition and stop_condition():
            return
        worked = False
        with contextlib.suppress(Exception):
            worked = await process_one_job(bot)
        if not worked:
            await asyncio.sleep(sleep_seconds)

