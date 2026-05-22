from __future__ import annotations

import traceback

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Job
from app.runtime import RuntimeConfig, get_runtime_config
from app.services.ai import AIProviderRouter
from app.services.jobs import complete_job, fail_job, update_job_progress
from app.services.knowledge import KnowledgeBase
from app.services.pdf import PDFRenderer, plan_to_markdown
from app.services.telegram import TelegramMessenger


def progress_text(step: str, percent: int, detail: str = "") -> str:
    filled = max(0, min(10, percent // 10))
    bar = "■" * filled + "□" * (10 - filled)
    lines = [
        "Работаю над контент-планом",
        "",
        f"[{bar}] {percent}%",
        step,
    ]
    if detail:
        lines.extend(["", detail])
    return "\n".join(lines)


class ReportPipeline:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.ai_router = AIProviderRouter()
        self.pdf_renderer = PDFRenderer()

    async def _set_progress(
        self,
        session: AsyncSession,
        messenger: TelegramMessenger,
        job: Job,
        text: str,
    ) -> None:
        await update_job_progress(session, job, text)
        await messenger.edit_progress(job.chat_id, job.progress_message_id, text)

    async def run(self, session: AsyncSession, job: Job) -> None:
        messenger = TelegramMessenger(self.bot)
        try:
            settings = get_settings()
            config = await get_runtime_config(session)
            knowledge = KnowledgeBase(config.obsidian_vault_path, settings.knowledge_index_file)

            await self._set_progress(
                session,
                messenger,
                job,
                progress_text("Изучаю задачу и готовлю поисковые запросы.", 10),
            )

            if not settings.knowledge_index_file.exists():
                await self._set_progress(
                    session,
                    messenger,
                    job,
                    progress_text("Индексирую Obsidian vault перед первым запуском.", 20),
                )
                await knowledge.rebuild_index(session)

            await self._set_progress(
                session,
                messenger,
                job,
                progress_text("Ищу в базе знаний бренд, ЦА, офферы, стиль и примеры.", 35),
            )
            snippets = knowledge.search(job.task_text, limit=config.max_knowledge_snippets)
            source_detail = f"Нашел фрагментов: {len(snippets)}." if snippets else "Релевантных фрагментов мало, аккуратно дополню план маркетинговой логикой."

            await self._set_progress(
                session,
                messenger,
                job,
                progress_text("Передаю контекст ИИ и собираю структуру плана.", 50, source_detail),
            )
            plan, provider, errors = await self.ai_router.generate_plan(job.task_text, snippets, config)
            if errors:
                plan.recommendations.append("Техническая заметка: часть AI-провайдеров была недоступна, сработал fallback.")

            await self._set_progress(
                session,
                messenger,
                job,
                progress_text("Верстаю PDF: обложка, стратегия, календарь, посты и визуальные промпты.", 75),
            )
            pdf_path, html_path = await self.pdf_renderer.render(plan, config, provider)

            await self._set_progress(
                session,
                messenger,
                job,
                progress_text("Сохраняю результат в Obsidian и готовлю отправку в Telegram.", 90),
            )
            markdown = plan_to_markdown(plan, provider, pdf_path)
            markdown_path = knowledge.save_markdown_report(plan.project, markdown)

            await messenger.delete_progress(job.chat_id, job.progress_message_id)
            caption = (
                f"Готово: {plan.project}\n"
                f"Период: {plan.period_days} дней\n"
                f"AI: {provider}\n\n"
                "Внутри PDF: стратегия, календарь, готовые тексты, CTA и промпты для визуалов."
            )
            await messenger.send_report(job.chat_id, pdf_path, caption)
            await complete_job(
                session,
                job,
                pdf_path=pdf_path,
                html_path=html_path,
                markdown_path=markdown_path,
                summary=plan.executive_summary,
            )
        except Exception as exc:  # noqa: BLE001 - pipeline must report errors to user
            error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            await fail_job(session, job, error)
            await messenger.edit_progress(
                job.chat_id,
                job.progress_message_id,
                "Не получилось завершить задачу.\n\n"
                f"Ошибка: {error}\n\n"
                "Проверьте настройки в админке: Telegram token, AI keys, Obsidian path и Playwright Chromium.",
            )

