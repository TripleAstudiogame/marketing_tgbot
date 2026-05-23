from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, utc_now

STALE_JOB_MINUTES = 30


async def create_job(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    username: str,
    task_text: str,
    progress_message_id: int | None,
) -> Job:
    job = Job(
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        task_text=task_text,
        status=JobStatus.pending,
        progress_message_id=progress_message_id,
        progress_text="Задача поставлена в очередь.",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def recover_stale_jobs(session: AsyncSession, older_than_minutes: int = STALE_JOB_MINUTES) -> int:
    cutoff = utc_now() - timedelta(minutes=older_than_minutes)
    result = await session.execute(
        update(Job)
        .where(Job.status == JobStatus.running, Job.updated_at < cutoff)
        .values(status=JobStatus.pending, updated_at=utc_now())
    )
    await session.commit()
    return result.rowcount or 0


async def get_next_pending_job(session: AsyncSession) -> Job | None:
    id_result = await session.execute(
        select(Job.id)
        .where(Job.status == JobStatus.pending)
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    job_id = id_result.scalar_one_or_none()
    if job_id is None:
        return None

    result = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.pending)
        .values(
            status=JobStatus.running,
            attempts=Job.attempts + 1,
            updated_at=utc_now(),
        )
        .returning(Job)
    )
    job = result.scalar_one_or_none()
    if job is None:
        await session.rollback()
        return None
    await session.commit()
    await session.refresh(job)
    return job


async def update_job_progress(session: AsyncSession, job: Job, text: str) -> None:
    job.progress_text = text
    job.updated_at = utc_now()
    await session.commit()


async def complete_job(
    session: AsyncSession,
    job: Job,
    pdf_path: str,
    html_path: str,
    markdown_path: str,
    summary: str,
) -> None:
    job.status = JobStatus.completed
    job.result_pdf_path = pdf_path
    job.result_html_path = html_path
    job.result_markdown_path = markdown_path
    job.result_summary = summary
    job.updated_at = utc_now()
    await session.commit()


async def fail_job(session: AsyncSession, job: Job, error: str) -> None:
    job.status = JobStatus.failed
    job.error = error
    job.updated_at = utc_now()
    await session.commit()


async def retry_job(session: AsyncSession, job: Job) -> None:
    job.status = JobStatus.pending
    job.error = ""
    job.updated_at = utc_now()
    await session.commit()


async def cancel_job(session: AsyncSession, job: Job) -> None:
    if job.status in {JobStatus.completed, JobStatus.failed}:
        return
    job.status = JobStatus.canceled
    job.updated_at = utc_now()
    await session.commit()


def jobs_query() -> Select[tuple[Job]]:
    return select(Job).order_by(Job.created_at.desc())
