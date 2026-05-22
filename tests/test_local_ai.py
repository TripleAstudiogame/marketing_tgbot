from __future__ import annotations

import pytest

from app.runtime import RuntimeConfig
from app.services.ai import LocalFallbackProvider


@pytest.mark.asyncio
async def test_local_fallback_generates_plan() -> None:
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
    plan = await LocalFallbackProvider().generate_plan("Сделай контент-план на 14 дней", [], config)
    assert plan.project == "Test Brand"
    assert len(plan.calendar) == 14
    assert plan.calendar[0].hook
