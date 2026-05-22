from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from app.runtime import RuntimeConfig
from app.schemas import CalendarItem, ContentPlan, ContentStrategy, KnowledgeSnippet


class AIProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    name: str

    @abstractmethod
    async def generate_plan(self, task_text: str, snippets: list[KnowledgeSnippet], config: RuntimeConfig) -> ContentPlan:
        raise NotImplementedError


def strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    return match.group(0) if match else cleaned


def parse_plan(text: str) -> ContentPlan:
    payload = json.loads(strip_json_fence(text))
    return ContentPlan.model_validate(payload)


def build_prompt(task_text: str, snippets: list[KnowledgeSnippet], config: RuntimeConfig) -> str:
    knowledge_block = "\n\n".join(
        f"Источник: {snippet.source_path}\nЗаголовок: {snippet.title}\nФрагмент:\n{snippet.text}"
        for snippet in snippets
    )
    if not knowledge_block:
        knowledge_block = "База знаний пока пустая или не проиндексирована. Используй здравую маркетинговую структуру и явно отметь, что данных мало."

    return f"""
Ты senior marketing strategist, content lead и editorial planner.
Твоя задача: создать практичный, живой и готовый к публикации контент-план для бизнеса.

Работай строго по вводным пользователя и базе знаний Obsidian.
Если в базе знаний есть факты о бренде, аудитории, офферах, стиле, конкурентах, используй их.
Если данных не хватает, делай аккуратные предположения и добавь рекомендации, что нужно уточнить.

Задача пользователя:
{task_text}

База знаний Obsidian:
{knowledge_block}

Верни только валидный JSON без Markdown.
Структура JSON:
{{
  "project": "название проекта или бизнеса",
  "goal": "главная цель",
  "period_days": 14,
  "executive_summary": "короткое резюме стратегии",
  "strategy": {{
    "positioning": "позиционирование",
    "audience": "целевая аудитория",
    "tone": "тон коммуникации",
    "content_pillars": ["рубрика 1", "рубрика 2", "рубрика 3"],
    "key_offers": ["оффер 1", "оффер 2"]
  }},
  "calendar": [
    {{
      "day": 1,
      "platform": "Telegram",
      "format": "пост / сторис / reels / email / статья",
      "topic": "тема",
      "hook": "сильный первый экран или первая строка",
      "post_text": "готовый текст публикации",
      "visual_prompt": "промпт для красивого визуала",
      "cta": "призыв к действию"
    }}
  ],
  "recommendations": ["рекомендация 1", "рекомендация 2"],
  "sources": ["список использованных файлов Obsidian"]
}}

Требования:
- Пиши на русском.
- Сделай минимум 14 дней, если пользователь не просил иначе.
- Если пользователь просит 30 дней, сделай 30 дней.
- Посты должны звучать живо, не как шаблонный ИИ.
- Не выдумывай конкретные факты о компании, если их нет в базе.
- Каждый день должен иметь конкретную тему, hook, текст, visual_prompt и CTA.
- В visual_prompt описывай стиль, композицию, объект, настроение и формат.
""".strip()


class GeminiProvider(AIProvider):
    name = "gemini"

    async def generate_plan(self, task_text: str, snippets: list[KnowledgeSnippet], config: RuntimeConfig) -> ContentPlan:
        if not config.gemini_api_key:
            raise AIProviderError("Gemini API key is not configured")
        prompt = build_prompt(task_text, snippets, config)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.gemini_model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.65,
                "responseMimeType": "application/json",
            },
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(url, params={"key": config.gemini_api_key}, json=payload)
        if response.status_code >= 400:
            raise AIProviderError(f"Gemini failed: {response.status_code} {response.text[:300]}")
        data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return parse_plan(text)
        except (KeyError, IndexError, ValidationError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"Gemini returned invalid plan: {exc}") from exc


class OpenAICompatibleProvider(AIProvider):
    base_url: str
    api_key_attr: str
    model_attr: str

    def __init__(self, name: str, base_url: str, api_key_attr: str, model_attr: str):
        self.name = name
        self.base_url = base_url
        self.api_key_attr = api_key_attr
        self.model_attr = model_attr

    async def generate_plan(self, task_text: str, snippets: list[KnowledgeSnippet], config: RuntimeConfig) -> ContentPlan:
        api_key = getattr(config, self.api_key_attr)
        model = getattr(config, self.model_attr)
        if not api_key:
            raise AIProviderError(f"{self.name} API key is not configured")
        prompt = build_prompt(task_text, snippets, config)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "http://localhost"
            headers["X-Title"] = "Marketing Telegram Bot"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only valid JSON. No Markdown."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.65,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        if response.status_code >= 400:
            raise AIProviderError(f"{self.name} failed: {response.status_code} {response.text[:300]}")
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
            return parse_plan(text)
        except (KeyError, IndexError, ValidationError, json.JSONDecodeError) as exc:
            raise AIProviderError(f"{self.name} returned invalid plan: {exc}") from exc


class LocalFallbackProvider(AIProvider):
    name = "local"

    async def generate_plan(self, task_text: str, snippets: list[KnowledgeSnippet], config: RuntimeConfig) -> ContentPlan:
        sources = sorted({snippet.source_path for snippet in snippets})
        context_note = snippets[0].text[:240] if snippets else "База знаний не найдена или пока не проиндексирована."
        period_days = 30 if re.search(r"\b30\b|30\s*д", task_text, re.IGNORECASE) else 14
        pillars = ["Экспертность", "Доверие", "Продажи", "Сообщество"]
        formats = ["пост", "кейс", "чеклист", "история", "разбор", "опрос", "продающий пост"]
        calendar: list[CalendarItem] = []
        for day in range(1, period_days + 1):
            pillar = pillars[(day - 1) % len(pillars)]
            fmt = formats[(day - 1) % len(formats)]
            topic = f"{pillar}: тема дня {day}"
            calendar.append(
                CalendarItem(
                    day=day,
                    platform="Telegram",
                    format=fmt,
                    topic=topic,
                    hook=f"Что важно знать перед тем, как решать задачу: {task_text[:80]}",
                    post_text=(
                        f"Сегодня разбираем направление '{pillar}'. "
                        f"Опираемся на задачу: {task_text}. "
                        f"Ключевая мысль из базы: {context_note} "
                        "Покажите конкретный пример, дайте один полезный совет и завершите мягким приглашением к диалогу."
                    ),
                    visual_prompt=(
                        "clean editorial social media visual, premium but warm, clear hierarchy, "
                        f"topic about {pillar}, brand colors, high readability"
                    ),
                    cta="Напишите в ответ, какую задачу разобрать следующей.",
                )
            )
        return ContentPlan(
            project=config.brand_name,
            goal=f"Собрать контент-план под задачу: {task_text}",
            period_days=period_days,
            executive_summary="План создан локальным fallback-генератором. Для более сильных текстов подключите Gemini, Groq или OpenRouter в админке.",
            strategy=ContentStrategy(
                positioning="Практичный экспертный бренд, который объясняет сложное простым языком и ведет аудиторию к действию.",
                audience="Целевая аудитория уточняется по базе знаний Obsidian и брифу пользователя.",
                tone="Живой, уверенный, полезный, без канцелярита.",
                content_pillars=pillars,
                key_offers=["Консультация", "Диагностика", "Подбор решения"],
            ),
            calendar=calendar,
            recommendations=[
                "Добавьте в Obsidian отдельные заметки про ЦА, офферы, tone of voice и примеры хороших постов.",
                "После подключения облачного LLM перегенерируйте план для более точного стиля.",
            ],
            sources=sources,
        )


class AIProviderRouter:
    def __init__(self) -> None:
        self.providers: dict[str, AIProvider] = {
            "gemini": GeminiProvider(),
            "groq": OpenAICompatibleProvider(
                name="groq",
                base_url="https://api.groq.com/openai/v1",
                api_key_attr="groq_api_key",
                model_attr="groq_model",
            ),
            "openrouter": OpenAICompatibleProvider(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key_attr="openrouter_api_key",
                model_attr="openrouter_model",
            ),
            "local": LocalFallbackProvider(),
        }

    async def generate_plan(self, task_text: str, snippets: list[KnowledgeSnippet], config: RuntimeConfig) -> tuple[ContentPlan, str, list[str]]:
        errors: list[str] = []
        for provider_name in config.ai_provider_order:
            provider = self.providers.get(provider_name)
            if provider is None:
                errors.append(f"Unknown provider: {provider_name}")
                continue
            try:
                return await provider.generate_plan(task_text, snippets, config), provider.name, errors
            except Exception as exc:  # noqa: BLE001 - router must continue to fallback providers
                errors.append(f"{provider.name}: {exc}")
                continue
        provider = self.providers["local"]
        plan = await provider.generate_plan(task_text, snippets, config)
        errors.append("All configured providers failed; local fallback was used.")
        return plan, provider.name, errors

