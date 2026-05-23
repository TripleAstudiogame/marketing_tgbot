from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import get_session
from app.models import BotAccessStatus, Job, JobStatus, KnowledgeDocument
from app.runtime import get_runtime_config, get_runtime_settings, get_settings_for_admin, parse_bool, update_runtime_settings
from app.services.access import (
    approve_access_request,
    count_pending_requests,
    list_access_requests,
    reject_access_request,
    revoke_access,
)
from app.services.env_file import update_env_file
from app.services.diagnostics import collect_diagnostics
from app.services.jobs import cancel_job, jobs_query, retry_job
from app.services.knowledge import KnowledgeBase
from app.services.memory import MemoryService
from app.services.vault_discovery import discover_vaults, list_directories
from app.worker import worker_state


admin_router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    settings = get_settings()
    username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def form_bool(value: object) -> str:
    return "true" if str(value or "").lower() in {"1", "true", "yes", "on"} else "false"


def configured_secret(value: str) -> bool:
    return bool(str(value or "").strip())


def setup_redirect(**params: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/setup?{urlencode(params)}", status_code=303)


async def check_telegram_token(token: str) -> tuple[bool, str]:
    if not token:
        return False, "токен пустой"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        if response.status_code >= 400:
            return False, f"Telegram вернул HTTP {response.status_code}"
        data = response.json()
        if not data.get("ok"):
            return False, data.get("description", "проверка Telegram-токена не прошла")
        user = data.get("result", {})
        username = user.get("username") or user.get("first_name") or "bot"
        return True, f"подключено как @{username}"
    except Exception as exc:  # noqa: BLE001 - admin check must not crash setup
        return False, f"проверка Telegram не прошла: {exc}"


async def check_ai_provider(provider: str, key: str, model: str) -> tuple[bool, str]:
    if provider != "local" and not key:
        return False, f"API-ключ {provider} пустой"
    try:
        async with httpx.AsyncClient(timeout=18) as client:
            if provider == "gemini":
                response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
            elif provider == "groq":
                response = await client.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"})
            elif provider == "openrouter":
                response = await client.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"})
            else:
                return True, "локальный fallback доступен; для лучшего контента подключи облачный ИИ"
        if response.status_code >= 400:
            return False, f"{provider} вернул HTTP {response.status_code}: {response.text[:160]}"
        suffix = f" Model: {model}." if model else ""
        return True, f"API-ключ {provider} выглядит рабочим.{suffix}"
    except Exception as exc:  # noqa: BLE001 - admin check must not crash setup
        return False, f"проверка {provider} не прошла: {exc}"


def ensure_starter_vault(path: Path) -> None:
    folders = [
        "00_Brand",
        "01_Audience",
        "02_Content",
        "03_Competitors",
        "04_Products",
        "05_Reports/generated_plans",
    ]
    for folder in folders:
        (path / folder).mkdir(parents=True, exist_ok=True)
    starter_files = {
        "00_Brand/brand.md": "# Brand\n\nНазвание:\n\nЧем занимаемся:\n\nЧто важно:\n",
        "00_Brand/tone_of_voice.md": "# Tone Of Voice\n\nСтиль общения:\n\nЗапрещенные формулировки:\n\nПримеры хорошего тона:\n",
        "00_Brand/offers.md": "# Offers\n\nГлавные офферы:\n\nЦены или пакеты:\n\nCTA:\n",
        "01_Audience/personas.md": "# Audience Personas\n\nКто наша аудитория:\n\nБоли:\n\nЖелания:\n\nВозражения:\n",
        "02_Content/hooks.md": "# Content Hooks\n\nСильные хуки:\n\nТемы, которые работают:\n",
        "03_Competitors/competitors.md": "# Competitors\n\nКонкуренты:\n\nЧто у них хорошо:\n\nЧем мы отличаемся:\n",
        "04_Products/products.md": "# Products\n\nПродукты или услуги:\n\nПольза:\n\nДля кого:\n",
    }
    for relative, content in starter_files.items():
        target = path / relative
        if not target.exists():
            target.write_text(content, encoding="utf-8")


@admin_router.get("", response_class=HTMLResponse)
@admin_router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    totals = {}
    for status_item in JobStatus:
        result = await session.execute(select(func.count()).select_from(Job).where(Job.status == status_item))
        totals[status_item.value] = result.scalar_one()
    docs_count = (await session.execute(select(func.count()).select_from(KnowledgeDocument))).scalar_one()
    pending_access = await count_pending_requests(session)
    latest_jobs = (await session.execute(jobs_query().limit(8))).scalars().all()
    runtime = await get_runtime_config(session)
    diagnostics = await collect_diagnostics(session, get_settings(), runtime)
    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "request": request,
            "totals": totals,
            "docs_count": docs_count,
            "pending_access": pending_access,
            "jobs": latest_jobs,
            "runtime": runtime,
            "settings": get_settings(),
            "diagnostics": diagnostics,
            "worker_state": worker_state,
        },
    )


@admin_router.get("/bot", response_class=HTMLResponse)
async def bot_access_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    pending = await list_access_requests(session, BotAccessStatus.pending)
    approved = await list_access_requests(session, BotAccessStatus.approved)
    rejected = await list_access_requests(session, BotAccessStatus.rejected, limit=20)
    return templates.TemplateResponse(
        request,
        "admin_bot.html",
        {
            "request": request,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "pending_count": len(pending),
        },
    )


async def _notify_access_decision(chat_id: int, approved: bool) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not chat_id:
        return
    try:
        from app.bot import create_bot

        bot = create_bot()
        if approved:
            text = (
                "Доступ одобрен!\n\n"
                "Теперь можно писать задачу одним сообщением — я соберу контент-план и отправлю PDF."
            )
        else:
            text = "Заявка на доступ отклонена. Если это ошибка — свяжитесь с администратором."
        await bot.send_message(chat_id, text)
        await bot.session.close()
    except Exception:  # noqa: BLE001 - notification must not break admin action
        return


@admin_router.post("/bot/{user_id}/approve")
async def approve_bot_access(
    user_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    record = await approve_access_request(session, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Access request not found")
    await _notify_access_decision(record.chat_id, approved=True)
    return RedirectResponse("/admin/bot?approved=1", status_code=303)


@admin_router.post("/bot/{user_id}/reject")
async def reject_bot_access(
    user_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    record = await reject_access_request(session, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Access request not found")
    await _notify_access_decision(record.chat_id, approved=False)
    return RedirectResponse("/admin/bot?rejected=1", status_code=303)


@admin_router.post("/bot/{user_id}/revoke")
async def revoke_bot_access(
    user_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    record = await revoke_access(session, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Access request not found")
    await _notify_access_decision(record.chat_id, approved=False)
    return RedirectResponse("/admin/bot?revoked=1", status_code=303)


@admin_router.get("/system", response_class=HTMLResponse)
async def system_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    settings = get_settings()
    runtime = await get_runtime_config(session)
    diagnostics = await collect_diagnostics(session, settings, runtime)
    log_files = []
    if settings.logs_path.exists():
        for path in sorted(settings.logs_path.glob("*.log")):
            log_files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": path.stat().st_size,
                    "updated": path.stat().st_mtime,
                }
            )
    return templates.TemplateResponse(
        request,
        "admin_system.html",
        {
            "request": request,
            "settings": settings,
            "runtime": runtime,
            "diagnostics": diagnostics,
            "worker_state": worker_state,
            "log_files": log_files,
        },
    )


@admin_router.get("/setup", response_class=HTMLResponse)
async def setup_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    settings = get_settings()
    runtime = await get_runtime_config(session)
    stored = await get_runtime_settings(session)
    vault_path = Path(runtime.obsidian_vault_path).expanduser()
    memory = MemoryService(runtime.obsidian_vault_path, runtime.ai_memory_dir)
    docs_count = (await session.execute(select(func.count()).select_from(KnowledgeDocument))).scalar_one()
    telegram_token = stored.get("TELEGRAM_BOT_TOKEN", settings.telegram_bot_token)
    telegram_use_webhook = parse_bool(stored.get("TELEGRAM_USE_WEBHOOK", settings.telegram_use_webhook))
    public_base_url = stored.get("PUBLIC_BASE_URL", settings.public_base_url)
    provider_status = {
        "gemini": configured_secret(stored.get("GEMINI_API_KEY", settings.gemini_api_key)),
        "groq": configured_secret(stored.get("GROQ_API_KEY", settings.groq_api_key)),
        "openrouter": configured_secret(stored.get("OPENROUTER_API_KEY", settings.openrouter_api_key)),
        "local": True,
    }
    return templates.TemplateResponse(
        request,
        "admin_setup.html",
        {
            "request": request,
            "settings": settings,
            "runtime": runtime,
            "stored": stored,
            "telegram_configured": configured_secret(telegram_token),
            "telegram_runtime_token": configured_secret(stored.get("TELEGRAM_BOT_TOKEN", "")),
            "telegram_use_webhook": telegram_use_webhook,
            "public_base_url": public_base_url,
            "vault_exists": vault_path.exists(),
            "vault_path": vault_path,
            "docs_count": docs_count,
            "memory_path": memory.memory_path,
            "memory_exists": memory.memory_path.exists(),
            "provider_status": provider_status,
            "vault_candidates": [],
        },
    )


@admin_router.get("/api/filesystem")
async def api_filesystem(
    path: str = "",
    _: str = Depends(require_admin),
) -> JSONResponse:
    data = await run_in_threadpool(list_directories, path or None)
    return JSONResponse(data)


@admin_router.get("/api/vaults/discover")
async def api_discover_vaults(
    _: str = Depends(require_admin),
) -> JSONResponse:
    candidates = await run_in_threadpool(discover_vaults, 3, 20)
    return JSONResponse({"candidates": candidates})


@admin_router.post("/setup/telegram")
async def setup_telegram(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    settings = get_settings()
    stored = await get_runtime_settings(session)
    token_input = str(form.get("TELEGRAM_BOT_TOKEN", "")).strip()
    values = {
        "TELEGRAM_USE_WEBHOOK": form_bool(form.get("TELEGRAM_USE_WEBHOOK")),
        "PUBLIC_BASE_URL": str(form.get("PUBLIC_BASE_URL", "")).strip(),
    }
    env_values = dict(values)
    if token_input:
        values["TELEGRAM_BOT_TOKEN"] = token_input
        env_values["TELEGRAM_BOT_TOKEN"] = token_input

    await update_runtime_settings(session, values)
    update_env_file(env_values)

    token = token_input or stored.get("TELEGRAM_BOT_TOKEN", "") or settings.telegram_bot_token
    ok, message = await check_telegram_token(token)
    if ok:
        return setup_redirect(telegram="ok", message=f"Настройки Telegram сохранены и проверены: {message}.")
    if token:
        return setup_redirect(
            telegram="warning",
            message=f"Настройки Telegram сохранены, но проверка токена не прошла: {message}.",
        )
    return setup_redirect(
        telegram="warning",
        message="Настройки Telegram сохранены. Добавь BotFather token, чтобы бот мог принимать задачи.",
    )


@admin_router.post("/setup/obsidian")
async def setup_obsidian(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    vault = Path(str(form.get("OBSIDIAN_VAULT_PATH", "")).strip()).expanduser()
    memory_enabled = form_bool(form.get("AI_MEMORY_ENABLED"))
    values = {
        "OBSIDIAN_VAULT_PATH": str(vault),
        "AI_MEMORY_ENABLED": memory_enabled,
        "AI_MEMORY_DIR": str(form.get("AI_MEMORY_DIR", "06_AI_Memory")).strip() or "06_AI_Memory",
        "AI_MEMORY_MIN_IMPORTANCE": str(form.get("AI_MEMORY_MIN_IMPORTANCE", "2")).strip() or "2",
        "AI_MEMORY_AUTO_REINDEX": form_bool(form.get("AI_MEMORY_AUTO_REINDEX")),
    }
    if form.get("CREATE_VAULT"):
        vault.mkdir(parents=True, exist_ok=True)
        ensure_starter_vault(vault)
    await update_runtime_settings(session, values)
    update_env_file(values)

    if parse_bool(memory_enabled):
        MemoryService(str(vault), values["AI_MEMORY_DIR"]).initialize()

    if vault.exists():
        result = await KnowledgeBase(str(vault), get_settings().knowledge_index_file).rebuild_index(session)
        return setup_redirect(obsidian="ok", message=f"Indexed {result['documents']} docs and {result['chunks']} chunks.")
    return setup_redirect(obsidian="error", message="Vault folder does not exist. Enable Create folders or choose an existing vault.")


@admin_router.post("/setup/ai")
async def setup_ai(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    settings = get_settings()
    stored = await get_runtime_settings(session)
    values = {
        "AI_PROVIDER_ORDER": str(form.get("AI_PROVIDER_ORDER", "gemini,groq,openrouter,local")).strip(),
        "GEMINI_MODEL": str(form.get("GEMINI_MODEL", settings.gemini_model)).strip(),
        "GROQ_MODEL": str(form.get("GROQ_MODEL", settings.groq_model)).strip(),
        "OPENROUTER_MODEL": str(form.get("OPENROUTER_MODEL", settings.openrouter_model)).strip(),
        "MAX_KNOWLEDGE_SNIPPETS": str(form.get("MAX_KNOWLEDGE_SNIPPETS", settings.max_knowledge_snippets)).strip(),
    }
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        candidate = str(form.get(key, "")).strip()
        if candidate:
            values[key] = candidate

    await update_runtime_settings(session, values)
    update_env_file(values)

    provider = str(form.get("test_provider", "none")).strip()
    if provider in {"gemini", "groq", "openrouter", "local"}:
        key_map = {
            "gemini": values.get("GEMINI_API_KEY") or stored.get("GEMINI_API_KEY", settings.gemini_api_key),
            "groq": values.get("GROQ_API_KEY") or stored.get("GROQ_API_KEY", settings.groq_api_key),
            "openrouter": values.get("OPENROUTER_API_KEY") or stored.get("OPENROUTER_API_KEY", settings.openrouter_api_key),
            "local": "",
        }
        model_map = {
            "gemini": values["GEMINI_MODEL"],
            "groq": values["GROQ_MODEL"],
            "openrouter": values["OPENROUTER_MODEL"],
            "local": "local",
        }
        ok, message = await check_ai_provider(provider, key_map[provider], model_map[provider])
        if ok:
            return setup_redirect(ai="ok", message=f"Настройки ИИ сохранены и проверены: {message}.")
        return setup_redirect(ai="warning", message=f"Настройки ИИ сохранены, но проверка не прошла: {message}.")
    return setup_redirect(ai="ok", message="Настройки ИИ сохранены.")


@admin_router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    items = await get_settings_for_admin(session)
    return templates.TemplateResponse(request, "admin_settings.html", {"request": request, "items": items})


@admin_router.post("/settings")
async def save_settings(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    items = await get_settings_for_admin(session)
    values = {str(item["key"]): str(form.get(str(item["key"]), "")) for item in items}
    await update_runtime_settings(session, values)
    update_env_file(values)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@admin_router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(
    request: Request,
    q: str = "",
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    runtime = await get_runtime_config(session)
    knowledge = KnowledgeBase(runtime.obsidian_vault_path, get_settings().knowledge_index_file)
    docs = (await session.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.path.asc()).limit(200))).scalars().all()
    results = knowledge.search(q, limit=12) if q else []
    return templates.TemplateResponse(
        request,
        "admin_knowledge.html",
        {
            "request": request,
            "q": q,
            "docs": docs,
            "results": results,
            "runtime": runtime,
            "index_exists": get_settings().knowledge_index_file.exists(),
        },
    )


@admin_router.post("/knowledge/reindex")
async def reindex_knowledge(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    runtime = await get_runtime_config(session)
    knowledge = KnowledgeBase(runtime.obsidian_vault_path, get_settings().knowledge_index_file)
    await knowledge.rebuild_index(session)
    return RedirectResponse("/admin/knowledge?reindexed=1", status_code=303)


@admin_router.get("/memory", response_class=HTMLResponse)
async def memory_page(
    request: Request,
    file: str = "",
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    runtime = await get_runtime_config(session)
    memory = MemoryService(runtime.obsidian_vault_path, runtime.ai_memory_dir)
    files: list[dict[str, str | int]] = []
    selected_content = ""
    selected_file = ""

    if memory.memory_path.exists():
        for path in sorted(memory.memory_path.rglob("*.md")):
            relative = str(path.relative_to(memory.memory_path)).replace("\\", "/")
            files.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "updated": path.stat().st_mtime_ns,
                }
            )
        if file:
            candidate = (memory.memory_path / file).resolve()
            root = memory.memory_path.resolve()
            if root in candidate.parents or candidate == root:
                if candidate.exists() and candidate.suffix.lower() == ".md":
                    selected_file = str(candidate.relative_to(memory.memory_path)).replace("\\", "/")
                    selected_content = candidate.read_text(encoding="utf-8", errors="replace")[:50000]

    return templates.TemplateResponse(
        request,
        "admin_memory.html",
        {
            "request": request,
            "runtime": runtime,
            "memory_path": memory.memory_path,
            "files": files,
            "selected_file": selected_file,
            "selected_content": selected_content,
        },
    )


@admin_router.post("/memory/initialize")
async def initialize_memory(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    runtime = await get_runtime_config(session)
    memory = MemoryService(runtime.obsidian_vault_path, runtime.ai_memory_dir)
    memory.initialize()
    return RedirectResponse("/admin/memory?initialized=1", status_code=303)


@admin_router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    jobs = (await session.execute(jobs_query().limit(100))).scalars().all()
    return templates.TemplateResponse(request, "admin_jobs.html", {"request": request, "jobs": jobs})


@admin_router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse(request, "admin_job_detail.html", {"request": request, "job": job})


@admin_router.post("/jobs/{job_id}/retry")
async def retry_job_action(
    job_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await retry_job(session, job)
    return RedirectResponse(f"/admin/jobs/{job_id}", status_code=303)


@admin_router.post("/jobs/{job_id}/cancel")
async def cancel_job_action(
    job_id: int,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await cancel_job(session, job)
    return RedirectResponse(f"/admin/jobs/{job_id}", status_code=303)
