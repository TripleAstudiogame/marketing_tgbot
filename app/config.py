from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Marketing Telegram Bot"
    environment: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    public_base_url: str = ""
    secret_key: str = "change-this-long-random-secret"
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    run_worker_in_web: bool = True

    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    telegram_bot_token: str = ""
    telegram_use_webhook: bool = False
    telegram_webhook_secret: str = "change-this-webhook-secret"
    telegram_allowed_user_ids: str = ""

    obsidian_vault_path: str = r"C:\Obsidian\MarketingVault"
    knowledge_index_path: str = "./data/knowledge_index.json"

    ai_provider_order: str = "gemini,groq,openrouter,local"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.0-flash-exp:free"
    ai_request_timeout_seconds: int = 90

    pollinations_enabled: bool = False
    pollinations_base_url: str = "https://image.pollinations.ai/prompt"

    reports_dir: str = "./reports"
    logs_dir: str = "./logs"
    max_knowledge_snippets: int = 10

    ai_memory_enabled: bool = True
    ai_memory_dir: str = "06_AI_Memory"
    ai_memory_min_importance: int = 2
    ai_memory_auto_reindex: bool = True

    brand_primary_color: str = "#0f766e"
    brand_accent_color: str = "#f59e0b"
    brand_name: str = "Marketing Bot"

    @property
    def base_dir(self) -> Path:
        return Path.cwd()

    @property
    def reports_path(self) -> Path:
        return Path(self.reports_dir).expanduser().resolve()

    @property
    def logs_path(self) -> Path:
        return Path(self.logs_dir).expanduser().resolve()

    @property
    def knowledge_index_file(self) -> Path:
        return Path(self.knowledge_index_path).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, get_settings]
