from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.models import Job
from app.runtime import RuntimeConfig
from app.schemas import ContentPlan, MemoryUpdate


def _safe_title(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9А-Яа-яЁё_-]+", "_", value).strip("_")
    return slug[:80] or "memory"


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="utf-8")
        separator = "\n\n" if current.strip() else ""
        path.write_text(f"{current.rstrip()}{separator}{text.strip()}\n", encoding="utf-8")
    else:
        path.write_text(f"{text.strip()}\n", encoding="utf-8")


class MemoryService:
    def __init__(self, vault_path: str, memory_dir: str):
        self.vault_path = Path(vault_path).expanduser()
        self.memory_dir_name = memory_dir.strip("/\\") or "06_AI_Memory"
        self.memory_path = self.vault_path / self.memory_dir_name

    def enabled(self) -> bool:
        return self.vault_path.exists()

    def initialize(self) -> None:
        self.memory_path.mkdir(parents=True, exist_ok=True)
        (self.memory_path / "01_Work_Log").mkdir(parents=True, exist_ok=True)
        (self.memory_path / "02_Session_Notes").mkdir(parents=True, exist_ok=True)
        index = self.memory_path / "_index.md"
        if not index.exists():
            index.write_text(
                "# AI Memory\n\n"
                "This folder is written by the Telegram marketing bot.\n\n"
                "Files:\n"
                "- `marketer_profile.md` - durable preferences and working style.\n"
                "- `facts.md` - brand, audience, offer, style and workflow facts.\n"
                "- `followups.md` - missing data and future questions.\n"
                "- `01_Work_Log/` - chronological record of completed jobs.\n"
                "- `02_Session_Notes/` - one note per important completed task.\n",
                encoding="utf-8",
            )
        for filename, heading in {
            "marketer_profile.md": "Marketer Profile",
            "facts.md": "Durable Facts",
            "followups.md": "Follow-Up Questions",
        }.items():
            path = self.memory_path / filename
            if not path.exists():
                path.write_text(f"# {heading}\n\n", encoding="utf-8")

    def build_memory_markdown(
        self,
        job: Job,
        plan: ContentPlan,
        update: MemoryUpdate,
        provider: str,
        report_markdown_path: str,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tags = " ".join(f"#{tag.strip().replace(' ', '-')}" for tag in update.tags if tag.strip())
        lines = [
            "---",
            f"created: {now}",
            f"job_id: {job.id}",
            f"project: {plan.project}",
            f"provider: {provider}",
            f"importance: {update.importance}",
            "---",
            "",
            f"# Memory: {plan.project}",
            "",
            f"{tags}".strip(),
            "",
            "## Task",
            "",
            job.task_text,
            "",
            "## Why Remember",
            "",
            update.summary or "Useful work context for future marketing tasks.",
            "",
            "## Facts",
            "",
        ]
        if update.facts:
            lines.extend(f"- **{fact.category}** ({fact.confidence}): {fact.text}" for fact in update.facts)
        else:
            lines.append("- No durable facts extracted.")
        lines.extend(["", "## Follow-Ups", ""])
        if update.followups:
            lines.extend(f"- {item}" for item in update.followups)
        else:
            lines.append("- No follow-ups.")
        lines.extend(
            [
                "",
                "## Report",
                "",
                report_markdown_path or "Report was not saved to Obsidian.",
                "",
            ]
        )
        return "\n".join(lines)

    def write_update(
        self,
        job: Job,
        plan: ContentPlan,
        update: MemoryUpdate,
        provider: str,
        report_markdown_path: str,
        config: RuntimeConfig,
    ) -> list[str]:
        if not config.ai_memory_enabled or not update.should_write:
            return []
        if update.importance < config.ai_memory_min_importance:
            return []
        if not self.enabled():
            return []

        self.initialize()
        now = datetime.now()
        created_paths: list[str] = []

        session_title = f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{_safe_title(plan.project)}.md"
        session_path = self.memory_path / "02_Session_Notes" / session_title
        session_path.write_text(
            self.build_memory_markdown(job, plan, update, provider, report_markdown_path),
            encoding="utf-8",
        )
        created_paths.append(str(session_path))

        work_log_path = self.memory_path / "01_Work_Log" / f"{now.strftime('%Y-%m')}.md"
        _append(
            work_log_path,
            f"## {now.strftime('%Y-%m-%d %H:%M')} - Job #{job.id}: {plan.project}\n\n"
            f"- Task: {job.task_text}\n"
            f"- Period: {plan.period_days} days\n"
            f"- Provider: {provider}\n"
            f"- Summary: {update.summary or plan.executive_summary}\n"
            f"- Report: {report_markdown_path or '-'}\n",
        )
        created_paths.append(str(work_log_path))

        facts_by_category: dict[str, list[str]] = {}
        for fact in update.facts:
            facts_by_category.setdefault(fact.category, []).append(f"- ({fact.confidence}) {fact.text}")

        if facts_by_category:
            fact_lines = [f"## {now.strftime('%Y-%m-%d %H:%M')} - Job #{job.id}", ""]
            for category, facts in facts_by_category.items():
                fact_lines.extend([f"### {category}", "", *facts, ""])
            _append(self.memory_path / "facts.md", "\n".join(fact_lines))
            created_paths.append(str(self.memory_path / "facts.md"))

        profile_facts = [fact for fact in update.facts if fact.category in {"marketer", "style", "workflow"}]
        if profile_facts:
            profile_lines = [f"## {now.strftime('%Y-%m-%d %H:%M')} - Learned From Job #{job.id}", ""]
            profile_lines.extend(f"- ({fact.category}, {fact.confidence}) {fact.text}" for fact in profile_facts)
            _append(self.memory_path / "marketer_profile.md", "\n".join(profile_lines))
            created_paths.append(str(self.memory_path / "marketer_profile.md"))

        if update.followups:
            followup_lines = [f"## {now.strftime('%Y-%m-%d %H:%M')} - Job #{job.id}", ""]
            followup_lines.extend(f"- {item}" for item in update.followups)
            _append(self.memory_path / "followups.md", "\n".join(followup_lines))
            created_paths.append(str(self.memory_path / "followups.md"))

        return sorted(set(created_paths))

