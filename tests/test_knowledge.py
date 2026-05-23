from __future__ import annotations

from pathlib import Path

import pytest

from app.db import init_db
from app.services.knowledge import KnowledgeBase


@pytest.mark.asyncio
async def test_knowledge_index_and_search(tmp_path: Path) -> None:
    await init_db()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "brand.md").write_text(
        "# Brand\n\nМы премиальный салон красоты. Тон общения теплый и экспертный.",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    knowledge = KnowledgeBase(str(vault), index_path)

    from app.db import async_session_factory

    async with async_session_factory() as session:
        result = await knowledge.rebuild_index(session)

    assert result["documents"] == 1
    assert result["chunks"] >= 1
    found = knowledge.search("салон красоты тон общения", limit=3)
    assert found
    assert found[0].source_path == "brand.md"


@pytest.mark.asyncio
async def test_hybrid_rag_reads_obsidian_metadata_and_core_context(tmp_path: Path) -> None:
    await init_db()
    vault = tmp_path / "vault"
    (vault / "00_Brand").mkdir(parents=True)
    (vault / "01_Audience").mkdir(parents=True)
    (vault / "00_Brand" / "brand.md").write_text(
        "---\n"
        "title: Aurora Studio\n"
        "tags: [brand, positioning]\n"
        "---\n"
        "# Aurora Studio\n\n"
        "Премиальный салон красоты. Тон общения теплый, уверенный, экспертный. [[personas]]",
        encoding="utf-8",
    )
    (vault / "01_Audience" / "personas.md").write_text(
        "# Personas\n\n"
        "#audience Клиенты хотят выглядеть дороже без долгого ухода. Главные боли: мало времени и страх плохого результата.",
        encoding="utf-8",
    )

    index_path = tmp_path / "index.json"
    knowledge = KnowledgeBase(str(vault), index_path)

    from app.db import async_session_factory

    async with async_session_factory() as session:
        result = await knowledge.rebuild_index(session)

    assert result["documents"] == 2
    found = knowledge.search("сделай контент план для новой услуги и учти боли клиентов", limit=5)
    sources = {item.source_path for item in found}
    assert "00_Brand/brand.md" in sources
    assert "01_Audience/personas.md" in sources

    brand = next(item for item in found if item.source_path == "00_Brand/brand.md")
    assert "brand" in brand.tags
    assert brand.heading
    assert brand.chunk_id.endswith("#chunk-1")
    assert "personas" in brand.links
