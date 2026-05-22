from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.admin import admin_router
from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.db import init_db
from app.worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    settings.logs_path.mkdir(parents=True, exist_ok=True)
    await init_db()

    app.state.bot = None
    app.state.dispatcher = None
    app.state.worker_task = None

    if settings.telegram_bot_token:
        bot = create_bot()
        dispatcher = create_dispatcher()
        app.state.bot = bot
        app.state.dispatcher = dispatcher

        if settings.telegram_use_webhook and settings.public_base_url:
            webhook_url = f"{settings.public_base_url.rstrip('/')}/telegram/webhook/{settings.telegram_webhook_secret}"
            await bot.set_webhook(webhook_url)

        if settings.run_worker_in_web:
            app.state.worker_task = asyncio.create_task(worker_loop(bot))

    yield

    if app.state.worker_task:
        app.state.worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.worker_task

    if app.state.bot:
        if settings.telegram_use_webhook:
            with suppress(Exception):
                await app.state.bot.delete_webhook()
        await app.state.bot.session.close()


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
    app.include_router(admin_router)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/admin")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram/webhook/{secret}")
    async def telegram_webhook(secret: str, request: Request) -> dict[str, bool]:
        settings = get_settings()
        if secret != settings.telegram_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
        if not request.app.state.bot or not request.app.state.dispatcher:
            raise HTTPException(status_code=503, detail="Telegram bot is not configured")
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": request.app.state.bot})
        await request.app.state.dispatcher.feed_update(request.app.state.bot, update)
        return {"ok": True}

    return app

