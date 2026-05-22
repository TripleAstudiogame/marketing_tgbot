from __future__ import annotations

from pathlib import Path

from app.services.vault_discovery import discover_vaults, list_directories


def test_list_directories_falls_back_to_existing_parent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)

    result = list_directories(str(root / "missing" / "vault"))

    assert result["path"] == str(root)
    assert any(item["name"] == "child" for item in result["directories"])


def test_discover_vaults_finds_obsidian_folder(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "MarketingVault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "brand.md").write_text("# Brand", encoding="utf-8")
    monkeypatch.setattr("app.services.vault_discovery.candidate_roots", lambda: [tmp_path])

    candidates = discover_vaults(max_depth=2, max_results=5)

    assert candidates
    assert candidates[0]["path"] == str(vault)
