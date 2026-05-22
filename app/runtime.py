from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import RuntimeSetting, utc_now


SECRET_SETTING_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
}


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    description: str
    default_attr: str
    is_secret: bool = False


SETTING_DEFINITIONS: list[SettingDefinition] = [
    SettingDefinition("OBSIDIAN_VAULT_PATH", "Obsidian vault path", "Folder with Markdown notes.", "obsidian_vault_path"),
    SettingDefinition("TELEGRAM_ALLOWED_USER_IDS", "Allowed Telegram user IDs", "Comma-separated list. Empty means everyone can use the bot.", "telegram_allowed_user_ids"),
    SettingDefinition("AI_PROVIDER_ORDER", "AI provider order", "Comma-separated list: gemini, groq, openrouter, local.", "ai_provider_order"),
    SettingDefinition("GEMINI_API_KEY", "Gemini API key", "Recommended free-first LLM provider.", "gemini_api_key", True),
    SettingDefinition("GEMINI_MODEL", "Gemini model", "Example: gemini-2.5-flash.", "gemini_model"),
    SettingDefinition("GROQ_API_KEY", "Groq API key", "Fast fallback provider.", "groq_api_key", True),
    SettingDefinition("GROQ_MODEL", "Groq model", "Example: llama-3.3-70b-versatile.", "groq_model"),
    SettingDefinition("OPENROUTER_API_KEY", "OpenRouter API key", "Fallback provider for free models.", "openrouter_api_key", True),
    SettingDefinition("OPENROUTER_MODEL", "OpenRouter model", "Example: google/gemini-2.0-flash-exp:free.", "openrouter_model"),
    SettingDefinition("MAX_KNOWLEDGE_SNIPPETS", "Max knowledge snippets", "How many Obsidian snippets to send to the LLM.", "max_knowledge_snippets"),
    SettingDefinition("AI_MEMORY_ENABLED", "AI memory enabled", "true/false. Let the bot write durable memory notes into Obsidian.", "ai_memory_enabled"),
    SettingDefinition("AI_MEMORY_DIR", "AI memory folder", "Folder inside the Obsidian vault for durable bot memory.", "ai_memory_dir"),
    SettingDefinition("AI_MEMORY_MIN_IMPORTANCE", "AI memory min importance", "Only write memories with this importance or higher, from 1 to 5.", "ai_memory_min_importance"),
    SettingDefinition("AI_MEMORY_AUTO_REINDEX", "Reindex after memory write", "true/false. Makes new memory available to the next task immediately.", "ai_memory_auto_reindex"),
    SettingDefinition("POLLINATIONS_ENABLED", "Pollinations images", "true/false. If false, PDF uses branded cards and visual prompts.", "pollinations_enabled"),
    SettingDefinition("BRAND_NAME", "Brand name", "Used in PDF cover and captions.", "brand_name"),
    SettingDefinition("BRAND_PRIMARY_COLOR", "Brand primary color", "Hex color for PDF.", "brand_primary_color"),
    SettingDefinition("BRAND_ACCENT_COLOR", "Brand accent color", "Hex color for PDF.", "brand_accent_color"),
]


@dataclass(frozen=True)
class RuntimeConfig:
    obsidian_vault_path: str
    telegram_allowed_user_ids: list[int]
    ai_provider_order: list[str]
    gemini_api_key: str
    gemini_model: str
    groq_api_key: str
    groq_model: str
    openrouter_api_key: str
    openrouter_model: str
    max_knowledge_snippets: int
    ai_memory_enabled: bool
    ai_memory_dir: str
    ai_memory_min_importance: int
    ai_memory_auto_reindex: bool
    pollinations_enabled: bool
    brand_name: str
    brand_primary_color: str
    brand_accent_color: str


def _stringify_default(settings: Settings, definition: SettingDefinition) -> str:
    value = getattr(settings, definition.default_attr)
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(value: str | int | None, default: int) -> int:
    try:
        return int(value) if value is not None and str(value).strip() else default
    except ValueError:
        return default


def parse_csv(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def parse_user_ids(value: str | Iterable[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",") if item.strip()]
    else:
        raw = [str(item).strip() for item in value if str(item).strip()]
    ids: list[int] = []
    for item in raw:
        try:
            ids.append(int(item))
        except ValueError:
            continue
    return ids


async def get_runtime_settings(session: AsyncSession) -> dict[str, str]:
    rows = await session.execute(select(RuntimeSetting))
    return {row.key: row.value for row in rows.scalars().all()}


async def get_settings_for_admin(session: AsyncSession) -> list[dict[str, str | bool]]:
    settings = get_settings()
    stored = await get_runtime_settings(session)
    items: list[dict[str, str | bool]] = []
    for definition in SETTING_DEFINITIONS:
        default_value = _stringify_default(settings, definition)
        value = stored.get(definition.key, default_value)
        items.append(
            {
                "key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "value": value,
                "default": default_value,
                "is_secret": definition.is_secret,
            }
        )
    return items


async def update_runtime_settings(session: AsyncSession, values: dict[str, str]) -> None:
    definitions = {item.key: item for item in SETTING_DEFINITIONS}
    for key, value in values.items():
        if key not in definitions:
            continue
        if definitions[key].is_secret and not value:
            continue
        existing = await session.get(RuntimeSetting, key)
        if existing:
            existing.value = value
            existing.updated_at = utc_now()
        else:
            session.add(RuntimeSetting(key=key, value=value, updated_at=utc_now()))
    await session.commit()


async def get_runtime_config(session: AsyncSession) -> RuntimeConfig:
    settings = get_settings()
    stored = await get_runtime_settings(session)

    def value(key: str, attr: str) -> str:
        return stored.get(key, _stringify_default(settings, next(item for item in SETTING_DEFINITIONS if item.key == key)))

    return RuntimeConfig(
        obsidian_vault_path=value("OBSIDIAN_VAULT_PATH", "obsidian_vault_path"),
        telegram_allowed_user_ids=parse_user_ids(value("TELEGRAM_ALLOWED_USER_IDS", "telegram_allowed_user_ids")),
        ai_provider_order=parse_csv(value("AI_PROVIDER_ORDER", "ai_provider_order")) or ["local"],
        gemini_api_key=value("GEMINI_API_KEY", "gemini_api_key"),
        gemini_model=value("GEMINI_MODEL", "gemini_model"),
        groq_api_key=value("GROQ_API_KEY", "groq_api_key"),
        groq_model=value("GROQ_MODEL", "groq_model"),
        openrouter_api_key=value("OPENROUTER_API_KEY", "openrouter_api_key"),
        openrouter_model=value("OPENROUTER_MODEL", "openrouter_model"),
        max_knowledge_snippets=parse_int(value("MAX_KNOWLEDGE_SNIPPETS", "max_knowledge_snippets"), settings.max_knowledge_snippets),
        ai_memory_enabled=parse_bool(value("AI_MEMORY_ENABLED", "ai_memory_enabled")),
        ai_memory_dir=value("AI_MEMORY_DIR", "ai_memory_dir"),
        ai_memory_min_importance=parse_int(value("AI_MEMORY_MIN_IMPORTANCE", "ai_memory_min_importance"), settings.ai_memory_min_importance),
        ai_memory_auto_reindex=parse_bool(value("AI_MEMORY_AUTO_REINDEX", "ai_memory_auto_reindex")),
        pollinations_enabled=parse_bool(value("POLLINATIONS_ENABLED", "pollinations_enabled")),
        brand_name=value("BRAND_NAME", "brand_name"),
        brand_primary_color=value("BRAND_PRIMARY_COLOR", "brand_primary_color"),
        brand_accent_color=value("BRAND_ACCENT_COLOR", "brand_accent_color"),
    )
