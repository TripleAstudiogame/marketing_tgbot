from __future__ import annotations

import traceback

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Job
from app.runtime import get_runtime_config
from app.services.ai import AIProviderRouter
from app.services.jobs import complete_job, fail_job, update_job_progress
from app.services.knowledge import KnowledgeBase
from app.services.memory import MemoryService
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


def merge_snippets(primary: list, secondary: list, limit: int) -> list:
    seen: set[tuple[str, str]] = set()
    merged: list = []
    for snippet in [*primary, *secondary]:
        key = (snippet.source_path, snippet.text[:120])
        if key in seen:
            continue
        seen.add(key)
        merged.append(snippet)
        if len(merged) >= limit:
            break
    return merged


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
            memory = MemoryService(config.obsidian_vault_path, config.ai_memory_dir)

            await self._set_progress(
                session,
                messenger,
                job,
                progress_text("Изучаю задачу и готовлю поисковые запросы.", 10),
            )

            if knowledge.needs_rebuild():
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
            if config.ai_memory_enabled:
                memory_snippets = knowledge.search(
                    "AI Memory память маркетолог профиль последние работы предпочтения стиль followups",
                    limit=max(3, config.max_knowledge_snippets // 2),
                )
                snippets = merge_snippets(snippets, memory_snippets, config.max_knowledge_snippets)
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

            if config.ai_memory_enabled:
                await self._set_progress(
                    session,
                    messenger,
                    job,
                    progress_text("Обновляю рабочую память в Obsidian, чтобы следующие задачи были умнее.", 95),
                )
                try:
                    memory_update, memory_provider, memory_errors = await self.ai_router.extract_memory_update(job.task_text, plan, snippets, config)
                    memory_paths = memory.write_update(job, plan, memory_update, memory_provider, markdown_path, config)
                    if memory_paths and config.ai_memory_auto_reindex:
                        await knowledge.rebuild_index(session)
                    if memory_errors:
                        plan.recommendations.append("Техническая заметка: память была обновлена через fallback-провайдер.")
                except Exception:
                    plan.recommendations.append("Техническая заметка: не удалось обновить долговременную память Obsidian.")

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
