from __future__ import annotations

from pathlib import Path

from app.services.env_file import update_env_file


def test_update_env_file_preserves_comments_and_updates_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nAPP_PORT=8000\nGEMINI_API_KEY=old\n", encoding="utf-8")

    update_env_file({"APP_PORT": "9000", "GROQ_API_KEY": "new-key"}, env)

    text = env.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "APP_PORT=9000" in text
    assert "GROQ_API_KEY=new-key" in text
    assert "GEMINI_API_KEY=old" in text

