from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeSnippet(BaseModel):
    source_path: str
    title: str
    text: str
    score: float = 0.0


class ContentStrategy(BaseModel):
    positioning: str = ""
    audience: str = ""
    tone: str = ""
    content_pillars: list[str] = Field(default_factory=list)
    key_offers: list[str] = Field(default_factory=list)


class CalendarItem(BaseModel):
    day: int
    platform: str = "Telegram"
    format: str = "post"
    topic: str
    hook: str
    post_text: str
    visual_prompt: str = ""
    cta: str = ""


class ContentPlan(BaseModel):
    project: str = "Marketing project"
    goal: str = ""
    period_days: int = 14
    executive_summary: str = ""
    strategy: ContentStrategy = Field(default_factory=ContentStrategy)
    calendar: list[CalendarItem] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class GeneratedReport(BaseModel):
    plan: ContentPlan
    provider: str
    pdf_path: str
    html_path: str
    markdown_path: str = ""


class MemoryFact(BaseModel):
    category: str = "general"
    text: str
    confidence: str = "medium"


class MemoryUpdate(BaseModel):
    should_write: bool = False
    importance: int = 1
    summary: str = ""
    facts: list[MemoryFact] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
