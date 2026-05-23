from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, BotAccessStatus
from app.runtime import RuntimeConfig
from app.services.access import (
    approve_access_request,
    submit_access_request,
    user_has_bot_access,
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def runtime_config(*, allowed: list[int] | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        obsidian_vault_path="/tmp/vault",
        telegram_allowed_user_ids=allowed or [],
        ai_provider_order=["local"],
        gemini_api_key="",
        gemini_model="",
        groq_api_key="",
        groq_model="",
        openrouter_api_key="",
        openrouter_model="",
        max_knowledge_snippets=5,
        ai_memory_enabled=True,
        ai_memory_dir="06_AI_Memory",
        ai_memory_min_importance=2,
        ai_memory_auto_reindex=True,
        pollinations_enabled=False,
        brand_name="Test",
        brand_primary_color="#0f766e",
        brand_accent_color="#f59e0b",
    )


@pytest.mark.asyncio
async def test_new_user_has_no_access(session: AsyncSession) -> None:
    assert not await user_has_bot_access(session, 42, runtime_config())


@pytest.mark.asyncio
async def test_submit_and_approve_access_request(session: AsyncSession) -> None:
    record = await submit_access_request(
        session,
        user_id=42,
        chat_id=100,
        username="tester",
        first_name="Test",
        last_name="User",
    )
    assert record.status == BotAccessStatus.pending
    assert not await user_has_bot_access(session, 42, runtime_config())

    await approve_access_request(session, 42)
    assert await user_has_bot_access(session, 42, runtime_config())


@pytest.mark.asyncio
async def test_legacy_allowed_ids_grant_access(session: AsyncSession) -> None:
    assert await user_has_bot_access(session, 7, runtime_config(allowed=[7]))
