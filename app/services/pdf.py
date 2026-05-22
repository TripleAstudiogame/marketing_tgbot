from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from app.runtime import RuntimeConfig
from app.schemas import ContentPlan


def safe_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9А-Яа-яЁё_-]+", "_", value).strip("_")
    return slug[:90] or "content_plan"


def plan_to_markdown(plan: ContentPlan, provider: str, pdf_path: str = "") -> str:
    lines = [
        "---",
        f"title: {plan.project}",
        f"created: {datetime.now().isoformat(timespec='seconds')}",
        f"provider: {provider}",
        "---",
        "",
        f"# {plan.project}",
        "",
        f"**Цель:** {plan.goal}",
        "",
        f"**Резюме:** {plan.executive_summary}",
        "",
        "## Стратегия",
        "",
        f"- Позиционирование: {plan.strategy.positioning}",
        f"- Аудитория: {plan.strategy.audience}",
        f"- Тон: {plan.strategy.tone}",
        f"- Рубрики: {', '.join(plan.strategy.content_pillars)}",
        f"- Офферы: {', '.join(plan.strategy.key_offers)}",
        "",
        "## Календарь",
        "",
    ]
    for item in plan.calendar:
        lines.extend(
            [
                f"### День {item.day}: {item.topic}",
                "",
                f"- Платформа: {item.platform}",
                f"- Формат: {item.format}",
                f"- Хук: {item.hook}",
                f"- CTA: {item.cta}",
                "",
                item.post_text,
                "",
                f"**Visual prompt:** {item.visual_prompt}",
                "",
            ]
        )
    if plan.recommendations:
        lines.extend(["## Рекомендации", ""])
        lines.extend(f"- {item}" for item in plan.recommendations)
        lines.append("")
    if plan.sources:
        lines.extend(["## Источники из Obsidian", ""])
        lines.extend(f"- {source}" for source in plan.sources)
        lines.append("")
    if pdf_path:
        lines.extend(["## PDF", "", pdf_path, ""])
    return "\n".join(lines)


class PDFRenderer:
    def __init__(self) -> None:
        settings = get_settings()
        self.reports_dir = settings.reports_path
        self.templates_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        )

    async def render(self, plan: ContentPlan, config: RuntimeConfig, provider: str) -> tuple[str, str]:
        from playwright.async_api import async_playwright

        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        basename = f"{timestamp}_{safe_filename(plan.project)}"
        html_path = self.reports_dir / f"{basename}.html"
        pdf_path = self.reports_dir / f"{basename}.pdf"

        template = self.env.get_template("report.html")
        html = template.render(
            plan=plan,
            config=config,
            provider=provider,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        html_path.write_text(html, encoding="utf-8")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1280, "height": 1800})
            await page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
            )
            await browser.close()

        return str(pdf_path), str(html_path)

