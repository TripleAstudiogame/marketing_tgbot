from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile


class TelegramMessenger:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def edit_progress(self, chat_id: int, message_id: int | None, text: str) -> None:
        if not message_id:
            return
        try:
            await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text[:4096])
        except TelegramAPIError:
            return

    async def delete_progress(self, chat_id: int, message_id: int | None) -> None:
        if not message_id:
            return
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramAPIError:
            return

    async def send_report(self, chat_id: int, pdf_path: str, caption: str) -> None:
        file = FSInputFile(str(Path(pdf_path)))
        await self.bot.send_document(chat_id=chat_id, document=file, caption=caption[:1024])

    async def send_text(self, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text[:4096])

