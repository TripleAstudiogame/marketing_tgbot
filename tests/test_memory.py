from __future__ import annotations

from pathlib import Path

from app.models import Job, JobStatus
from app.runtime import RuntimeConfig
from app.schemas import ContentPlan, ContentStrategy, MemoryFact, MemoryUpdate
from app.services.memory import MemoryService


def test_memory_service_writes_obsidian_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = RuntimeConfig(
        obsidian_vault_path=str(vault),
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
    job = Job(
        id=7,
        chat_id=1,
        user_id=2,
        username="tester",
        task_text="Сделай контент-план для эксперта",
        status=JobStatus.completed,
    )
    plan = ContentPlan(
        project="Expert Brand",
        goal="Grow trust",
        period_days=14,
        executive_summary="Useful plan.",
        strategy=ContentStrategy(tone="живой и экспертный", audience="предприниматели"),
    )
    update = MemoryUpdate(
        should_write=True,
        importance=3,
        summary="Запомнить стиль и аудиторию.",
        facts=[
            MemoryFact(category="style", text="Маркетолог предпочитает живой экспертный тон.", confidence="high"),
            MemoryFact(category="audience", text="ЦА проекта: предприниматели.", confidence="medium"),
        ],
        followups=["Уточнить главный продукт."],
        tags=["ai-memory", "test"],
    )

    paths = MemoryService(str(vault), "06_AI_Memory").write_update(
        job=job,
        plan=plan,
        update=update,
        provider="local",
        report_markdown_path="05_Reports/generated_plans/report.md",
        config=config,
    )

    assert paths
    assert (vault / "06_AI_Memory" / "facts.md").exists()
    assert (vault / "06_AI_Memory" / "marketer_profile.md").exists()
    assert "живой экспертный тон" in (vault / "06_AI_Memory" / "marketer_profile.md").read_text(encoding="utf-8")
