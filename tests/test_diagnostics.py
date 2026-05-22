from __future__ import annotations

import pytest

from app.config import get_settings
from app.db import async_session_factory, init_db
from app.runtime import RuntimeConfig
from app.services.diagnostics import collect_diagnostics


@pytest.mark.asyncio
async def test_collect_diagnostics_returns_status() -> None:
    await init_db()
    config = RuntimeConfig(
        obsidian_vault_path=".",
        telegram_allowed_user_ids=[],
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
        brand_name="Test Brand",
        brand_primary_color="#0f766e",
        brand_accent_color="#f59e0b",
    )
    async with async_session_factory() as session:
        diagnostics = await collect_diagnostics(session, get_settings(), config)

    assert diagnostics["status"] in {"ok", "warning", "error"}
    assert diagnostics["checks"]
