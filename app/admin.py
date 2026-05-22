from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Job, JobStatus, KnowledgeDocument
from app.runtime import get_runtime_config, get_settings_for_admin, update_runtime_settings
from app.services.jobs import cancel_job, jobs_query, retry_job
from app.services.knowledge import KnowledgeBase


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
    latest_jobs = (await session.execute(jobs_query().limit(8))).scalars().all()
    runtime = await get_runtime_config(session)
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "totals": totals,
            "docs_count": docs_count,
            "jobs": latest_jobs,
            "runtime": runtime,
            "settings": get_settings(),
        },
    )


@admin_router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    items = await get_settings_for_admin(session)
    return templates.TemplateResponse("admin_settings.html", {"request": request, "items": items})


@admin_router.post("/settings")
async def save_settings(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    OBSIDIAN_VAULT_PATH: str = Form(""),
    TELEGRAM_ALLOWED_USER_IDS: str = Form(""),
    AI_PROVIDER_ORDER: str = Form(""),
    GEMINI_API_KEY: str = Form(""),
    GEMINI_MODEL: str = Form(""),
    GROQ_API_KEY: str = Form(""),
    GROQ_MODEL: str = Form(""),
    OPENROUTER_API_KEY: str = Form(""),
    OPENROUTER_MODEL: str = Form(""),
    MAX_KNOWLEDGE_SNIPPETS: str = Form(""),
    POLLINATIONS_ENABLED: str = Form("false"),
    BRAND_NAME: str = Form(""),
    BRAND_PRIMARY_COLOR: str = Form(""),
    BRAND_ACCENT_COLOR: str = Form(""),
) -> RedirectResponse:
    values = {
        "OBSIDIAN_VAULT_PATH": OBSIDIAN_VAULT_PATH,
        "TELEGRAM_ALLOWED_USER_IDS": TELEGRAM_ALLOWED_USER_IDS,
        "AI_PROVIDER_ORDER": AI_PROVIDER_ORDER,
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "GEMINI_MODEL": GEMINI_MODEL,
        "GROQ_API_KEY": GROQ_API_KEY,
        "GROQ_MODEL": GROQ_MODEL,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
        "OPENROUTER_MODEL": OPENROUTER_MODEL,
        "MAX_KNOWLEDGE_SNIPPETS": MAX_KNOWLEDGE_SNIPPETS,
        "POLLINATIONS_ENABLED": POLLINATIONS_ENABLED,
        "BRAND_NAME": BRAND_NAME,
        "BRAND_PRIMARY_COLOR": BRAND_PRIMARY_COLOR,
        "BRAND_ACCENT_COLOR": BRAND_ACCENT_COLOR,
    }
    await update_runtime_settings(session, values)
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


@admin_router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    jobs = (await session.execute(jobs_query().limit(100))).scalars().all()
    return templates.TemplateResponse("admin_jobs.html", {"request": request, "jobs": jobs})


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
    return templates.TemplateResponse("admin_job_detail.html", {"request": request, "job": job})


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

