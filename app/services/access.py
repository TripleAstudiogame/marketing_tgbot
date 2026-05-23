from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BotAccessRequest, BotAccessStatus, utc_now
from app.runtime import RuntimeConfig


def display_name(record: BotAccessRequest) -> str:
    parts = [record.first_name, record.last_name]
    name = " ".join(part for part in parts if part).strip()
    if name:
        return name
    if record.username:
        return f"@{record.username}"
    return str(record.telegram_user_id)


async def get_access_request(session: AsyncSession, user_id: int) -> BotAccessRequest | None:
    return await session.get(BotAccessRequest, user_id)


async def user_has_bot_access(
    session: AsyncSession,
    user_id: int,
    config: RuntimeConfig,
) -> bool:
    if user_id in config.telegram_allowed_user_ids:
        return True
    record = await get_access_request(session, user_id)
    return record is not None and record.status == BotAccessStatus.approved


async def submit_access_request(
    session: AsyncSession,
    *,
    user_id: int,
    chat_id: int,
    username: str,
    first_name: str,
    last_name: str,
) -> BotAccessRequest:
    record = await get_access_request(session, user_id)
    if record and record.status == BotAccessStatus.approved:
        return record
    if record and record.status == BotAccessStatus.pending:
        record.chat_id = chat_id
        record.username = username
        record.first_name = first_name
        record.last_name = last_name
        record.updated_at = utc_now()
        await session.commit()
        await session.refresh(record)
        return record

    if record and record.status == BotAccessStatus.rejected:
        record.chat_id = chat_id
        record.username = username
        record.first_name = first_name
        record.last_name = last_name
        record.status = BotAccessStatus.pending
        record.reviewed_at = None
        record.updated_at = utc_now()
        await session.commit()
        await session.refresh(record)
        return record

    record = BotAccessRequest(
        telegram_user_id=user_id,
        chat_id=chat_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        status=BotAccessStatus.pending,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def approve_access_request(session: AsyncSession, user_id: int) -> BotAccessRequest | None:
    record = await get_access_request(session, user_id)
    if not record:
        return None
    record.status = BotAccessStatus.approved
    record.reviewed_at = utc_now()
    record.updated_at = utc_now()
    await session.commit()
    await session.refresh(record)
    return record


async def reject_access_request(session: AsyncSession, user_id: int) -> BotAccessRequest | None:
    record = await get_access_request(session, user_id)
    if not record:
        return None
    record.status = BotAccessStatus.rejected
    record.reviewed_at = utc_now()
    record.updated_at = utc_now()
    await session.commit()
    await session.refresh(record)
    return record


async def revoke_access(session: AsyncSession, user_id: int) -> BotAccessRequest | None:
    record = await get_access_request(session, user_id)
    if not record:
        return None
    record.status = BotAccessStatus.rejected
    record.reviewed_at = utc_now()
    record.updated_at = utc_now()
    await session.commit()
    await session.refresh(record)
    return record


async def list_access_requests(
    session: AsyncSession,
    status: BotAccessStatus | None = None,
    limit: int = 100,
) -> list[BotAccessRequest]:
    query = select(BotAccessRequest).order_by(BotAccessRequest.updated_at.desc()).limit(limit)
    if status is not None:
        query = query.where(BotAccessRequest.status == status)
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_pending_requests(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(BotAccessRequest)
        .where(BotAccessRequest.status == BotAccessStatus.pending)
    )
    return result.scalar_one()


async def sync_legacy_allowed_ids(session: AsyncSession, allowed_ids: list[int]) -> None:
    """Import env-based allowlist into approved access records."""
    for user_id in allowed_ids:
        record = await get_access_request(session, user_id)
        if record:
            if record.status != BotAccessStatus.approved:
                record.status = BotAccessStatus.approved
                record.reviewed_at = utc_now()
                record.updated_at = utc_now()
            continue
        session.add(
            BotAccessRequest(
                telegram_user_id=user_id,
                chat_id=user_id,
                status=BotAccessStatus.approved,
                reviewed_at=utc_now(),
            )
        )
    await session.commit()
