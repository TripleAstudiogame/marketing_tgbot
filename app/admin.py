from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.services.memory import MemoryService


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
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    items = await get_settings_for_admin(session)
    values = {str(item["key"]): str(form.get(str(item["key"]), "")) for item in items}
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
