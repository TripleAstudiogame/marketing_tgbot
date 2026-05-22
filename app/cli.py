from __future__ import annotations

import argparse
import asyncio

import uvicorn

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.db import init_db
from app.worker import worker_loop


async def run_polling_with_worker() -> None:
    await init_db()
    bot = create_bot()
    dispatcher = create_dispatcher()
    worker_task = asyncio.create_task(worker_loop(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker_task.cancel()
        await bot.session.close()


async def run_all() -> None:
    await init_db()
    settings = get_settings()
    settings.run_worker_in_web = False
    bot = create_bot()
    dispatcher = create_dispatcher()
    worker_task = asyncio.create_task(worker_loop(bot))
    polling_task = asyncio.create_task(dispatcher.start_polling(bot))
    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:create_app",
            host=settings.app_host,
            port=settings.app_port,
            factory=True,
            log_level="info",
        )
    )
    try:
        await server.serve()
    finally:
        polling_task.cancel()
        worker_task.cancel()
        await bot.session.close()


def run_web() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        host=settings.app_host,
        port=settings.app_port,
        factory=True,
        log_level="info",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing Telegram Bot CLI")
    parser.add_argument("command", choices=["web", "polling", "all", "init-db"], help="Command to run")
    args = parser.parse_args()

    if args.command == "web":
        run_web()
    elif args.command == "polling":
        asyncio.run(run_polling_with_worker())
    elif args.command == "all":
        asyncio.run(run_all())
    elif args.command == "init-db":
        asyncio.run(init_db())


if __name__ == "__main__":
    main()
