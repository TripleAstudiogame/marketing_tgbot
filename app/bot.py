from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import get_settings
from app.db import async_session_factory
from app.models import BotAccessStatus
from app.runtime import get_runtime_config
from app.services.access import get_access_request, submit_access_request, user_has_bot_access
from app.services.jobs import create_job

router = Router()

ACCESS_REQUEST_CALLBACK = "access:request"
ACCESS_DECLINE_CALLBACK = "access:decline"


def create_bot() -> Bot:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    return Bot(token=settings.telegram_bot_token)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router())
    return dispatcher


def create_router() -> Router:
    bot_router = Router()
    bot_router.message.register(start_command, CommandStart())
    bot_router.message.register(help_command, Command("help"))
    bot_router.callback_query.register(access_request_callback, F.data == ACCESS_REQUEST_CALLBACK)
    bot_router.callback_query.register(access_decline_callback, F.data == ACCESS_DECLINE_CALLBACK)
    bot_router.message.register(handle_task, F.text)
    return bot_router


def access_request_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, оставить заявку", callback_data=ACCESS_REQUEST_CALLBACK)],
            [InlineKeyboardButton(text="Не сейчас", callback_data=ACCESS_DECLINE_CALLBACK)],
        ]
    )


async def send_access_intro(message: Message) -> None:
    await message.answer(
        "Привет! Это бот для маркетинговых контент-планов.\n\n"
        "Сначала нужен доступ: администратор должен подтвердить вашу заявку.\n\n"
        "Хотите оставить заявку на доступ?",
        reply_markup=access_request_keyboard(),
    )


async def send_access_status(message: Message, status: BotAccessStatus) -> None:
    if status == BotAccessStatus.pending:
        await message.answer(
            "Заявка уже отправлена и ждёт подтверждения администратора.\n\n"
            "Когда доступ откроют — напишите задачу одним сообщением."
        )
        return
    if status == BotAccessStatus.rejected:
        await message.answer(
            "Доступ к боту пока не одобрен.\n\n"
            "Напишите /start, если хотите подать заявку снова."
        )
        return
    await send_access_intro(message)


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    user = message.from_user
    if user is None:
        await message.answer("Не удалось определить пользователя Telegram.")
        return

    async with async_session_factory() as session:
        config = await get_runtime_config(session)
        if await user_has_bot_access(session, user.id, config):
            await message.answer(
                "Привет! Я помогу собрать контент-план и отправлю PDF.\n\n"
                "Напишите задачу одним сообщением. Например:\n"
                "«Сделай контент-план на 30 дней для салона красоты, цель — больше записей»."
            )
            return

        record = await get_access_request(session, user.id)
        if record is None:
            await send_access_intro(message)
            return
        await send_access_status(message, record.status)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    async with async_session_factory() as session:
        config = await get_runtime_config(session)
        if not await user_has_bot_access(session, user.id, config):
            await message.answer(
                "Бот работает только после одобрения заявки администратором.\n"
                "Напишите /start, чтобы подать заявку."
            )
            return

    await message.answer(
        "Как пользоваться:\n"
        "1. Опишите бизнес, цель, период и площадки.\n"
        "2. Я найду вводные в Obsidian.\n"
        "3. Подготовлю PDF с планом, текстами и визуальными промптами."
    )


@router.callback_query(F.data == ACCESS_REQUEST_CALLBACK)
async def access_request_callback(callback: CallbackQuery) -> None:
    user = callback.from_user
    message = callback.message
    if user is None or message is None:
        return

    async with async_session_factory() as session:
        config = await get_runtime_config(session)
        if await user_has_bot_access(session, user.id, config):
            await callback.answer("У вас уже есть доступ.", show_alert=True)
            await message.answer(
                "Доступ уже открыт. Напишите задачу одним сообщением — начну работу."
            )
            return

        record = await get_access_request(session, user.id)
        if record and record.status == BotAccessStatus.pending:
            await callback.answer("Заявка уже на рассмотрении.")
            return
        if record and record.status == BotAccessStatus.rejected:
            pass  # allow resubmit below

        await submit_access_request(
            session,
            user_id=user.id,
            chat_id=message.chat.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
        )

    await callback.answer("Заявка отправлена.")
    await message.edit_reply_markup(reply_markup=None)
    await message.answer(
        "Заявка отправлена администратору.\n\n"
        "Когда доступ подтвердят — напишите задачу одним сообщением, и я начну работу."
    )


@router.callback_query(F.data == ACCESS_DECLINE_CALLBACK)
async def access_decline_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        return
    await callback.answer()
    await message.edit_reply_markup(reply_markup=None)
    await message.answer(
        "Хорошо. Когда будете готовы — напишите /start и оставьте заявку на доступ."
    )


@router.message(F.text)
async def handle_task(message: Message) -> None:
    if not message.text:
        return
    user = message.from_user
    if user is None:
        await message.answer("Не удалось определить пользователя Telegram.")
        return

    async with async_session_factory() as session:
        config = await get_runtime_config(session)
        if not await user_has_bot_access(session, user.id, config):
            record = await get_access_request(session, user.id)
            if record is None:
                await send_access_intro(message)
            else:
                await send_access_status(message, record.status)
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
