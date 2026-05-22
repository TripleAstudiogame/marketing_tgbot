from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.config import get_settings
from app.db import async_session_factory
from app.runtime import get_runtime_config
from app.services.jobs import create_job


router = Router()


def create_bot() -> Bot:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    return Bot(token=settings.telegram_bot_token)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(
        "Привет. Я маркетинг-бот: беру задачу, смотрю базу знаний Obsidian, "
        "делаю контент-план и отправляю PDF.\n\n"
        "Напишите задачу одним сообщением. Например:\n"
        "Сделай контент-план на 30 дней для салона красоты, цель - увеличить записи."
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Как пользоваться:\n"
        "1. Опишите бизнес, цель, период и площадки.\n"
        "2. Я найду вводные в Obsidian.\n"
        "3. Подготовлю PDF с планом, текстами и визуальными промптами.\n\n"
        "Админка доступна на сервере по адресу /admin."
    )


@router.message(F.text)
async def handle_task(message: Message) -> None:
    if not message.text:
        return
    user = message.from_user
    if user is None:
        await message.answer("Не смог определить пользователя Telegram.")
        return

    async with async_session_factory() as session:
        config = await get_runtime_config(session)
        if config.telegram_allowed_user_ids and user.id not in config.telegram_allowed_user_ids:
            await message.answer("У вас нет доступа к этому боту. Добавьте ваш Telegram user ID в админке.")
            return

        progress = await message.answer(
            "Принял задачу.\n\n"
            "[□□□□□□□□□□] 0%\n"
            "Ставлю задачу в очередь и готовлю рабочий контекст."
        )
        await create_job(
            session=session,
            chat_id=message.chat.id,
            user_id=user.id,
            username=user.username or "",
            task_text=message.text.strip(),
            progress_message_id=progress.message_id,
        )

