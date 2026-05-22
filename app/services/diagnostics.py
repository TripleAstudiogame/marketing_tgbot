from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Job, JobStatus, KnowledgeDocument
from app.runtime import RuntimeConfig


CheckLevel = Literal["ok", "warning", "error"]


def check(level: CheckLevel, name: str, detail: str, action: str = "") -> dict[str, str]:
    return {"level": level, "name": name, "detail": detail, "action": action}


def _can_write_file(folder: Path) -> bool:
    folder.mkdir(parents=True, exist_ok=True)
    probe = folder / ".write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return True


def overall_status(items: list[dict[str, str]]) -> str:
    if any(item["level"] == "error" for item in items):
        return "error"
    if any(item["level"] == "warning" for item in items):
        return "warning"
    return "ok"


async def collect_diagnostics(
    session: AsyncSession,
    settings: Settings,
    runtime: RuntimeConfig,
) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    try:
        await session.execute(text("select 1"))
        checks.append(check("ok", "Database", "Database connection is working."))
    except Exception as exc:  # noqa: BLE001
        checks.append(check("error", "Database", f"Database check failed: {exc}", "Check DATABASE_URL and file permissions."))

    try:
        _can_write_file(settings.reports_path)
        checks.append(check("ok", "Reports folder", f"Writable: {settings.reports_path}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(check("error", "Reports folder", f"Cannot write reports: {exc}", "Fix folder permissions."))

    try:
        _can_write_file(settings.logs_path)
        checks.append(check("ok", "Logs folder", f"Writable: {settings.logs_path}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(check("error", "Logs folder", f"Cannot write logs: {exc}", "Fix folder permissions."))

    vault = Path(runtime.obsidian_vault_path).expanduser()
    if vault.exists() and vault.is_dir():
        checks.append(check("ok", "Obsidian vault", f"Found: {vault}"))
    else:
        checks.append(check("warning", "Obsidian vault", f"Not found: {vault}", "Open /admin/setup and create or choose a vault folder."))

    docs_count = (await session.execute(select(func.count()).select_from(KnowledgeDocument))).scalar_one()
    if docs_count:
        checks.append(check("ok", "Knowledge index", f"{docs_count} Markdown documents indexed."))
    else:
        checks.append(check("warning", "Knowledge index", "No indexed documents yet.", "Open /admin/setup or /admin/knowledge and run reindex."))

    if settings.telegram_bot_token:
        checks.append(check("ok", "Telegram token", "Token is configured in .env."))
    else:
        checks.append(check("warning", "Telegram token", "Token is missing.", "Add BotFather token in /admin/setup and restart the app."))

    if runtime.gemini_api_key or runtime.groq_api_key or runtime.openrouter_api_key:
        providers = [
            name
            for name, enabled in {
                "Gemini": bool(runtime.gemini_api_key),
                "Groq": bool(runtime.groq_api_key),
                "OpenRouter": bool(runtime.openrouter_api_key),
            }.items()
            if enabled
        ]
        checks.append(check("ok", "Cloud AI", f"Configured: {', '.join(providers)}."))
    else:
        checks.append(check("warning", "Cloud AI", "No cloud AI key configured; local fallback will be used.", "Add Gemini API key in /admin/setup for best quality."))

    if runtime.ai_memory_enabled:
        memory_path = vault / runtime.ai_memory_dir
        if memory_path.exists():
            checks.append(check("ok", "AI memory", f"Memory folder exists: {memory_path}"))
        else:
            checks.append(check("warning", "AI memory", f"Memory folder not initialized: {memory_path}", "Open /admin/memory or /admin/setup."))
    else:
        checks.append(check("warning", "AI memory", "AI memory is disabled.", "Enable it in /admin/setup if you want durable memory."))

    try:
        import playwright  # noqa: F401

        checks.append(check("ok", "Playwright", "Python package is installed."))
    except Exception as exc:  # noqa: BLE001
        checks.append(check("error", "Playwright", f"Playwright import failed: {exc}", "Run scripts/setup_windows.ps1."))

    if settings.admin_password == "change-me-now":
        checks.append(check("warning", "Admin password", "Default admin password is still used.", "Change ADMIN_PASSWORD in .env."))
    else:
        checks.append(check("ok", "Admin password", "Admin password is customized."))

    running_jobs = (await session.execute(select(func.count()).select_from(Job).where(Job.status == JobStatus.running))).scalar_one()
    failed_jobs = (await session.execute(select(func.count()).select_from(Job).where(Job.status == JobStatus.failed))).scalar_one()

    return {
        "status": overall_status(checks),
        "checks": checks,
        "stats": {
            "indexed_documents": docs_count,
            "running_jobs": running_jobs,
            "failed_jobs": failed_jobs,
            "process_id": os.getpid(),
        },
    }

