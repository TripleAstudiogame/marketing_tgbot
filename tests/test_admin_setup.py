from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import admin


def test_telegram_setup_saves_settings_even_when_token_check_warns(monkeypatch) -> None:
    runtime_values: dict[str, str] = {}
    env_values: dict[str, str] = {}

    async def fake_session():
        yield object()

    async def fake_get_runtime_settings(_session):
        return {}

    async def fake_update_runtime_settings(_session, values):
        runtime_values.update(values)

    async def fake_check_telegram_token(token: str) -> tuple[bool, str]:
        assert token == "123456:BAD"
        return False, "Telegram вернул HTTP 401"

    monkeypatch.setattr(admin, "get_settings", lambda: SimpleNamespace(telegram_bot_token=""))
    monkeypatch.setattr(admin, "get_runtime_settings", fake_get_runtime_settings)
    monkeypatch.setattr(admin, "update_runtime_settings", fake_update_runtime_settings)
    monkeypatch.setattr(admin, "update_env_file", lambda values: env_values.update(values))
    monkeypatch.setattr(admin, "check_telegram_token", fake_check_telegram_token)

    app = FastAPI()
    app.include_router(admin.admin_router)
    app.dependency_overrides[admin.require_admin] = lambda: "admin"
    app.dependency_overrides[admin.get_session] = fake_session

    response = TestClient(app).post(
        "/admin/setup/telegram",
        data={
            "TELEGRAM_BOT_TOKEN": "123456:BAD",
            "PUBLIC_BASE_URL": "https://example.test",
            "TELEGRAM_USE_WEBHOOK": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["telegram"] == ["warning"]
    assert query["message"][0].startswith("Настройки Telegram сохранены")
    assert "проверка токена не прошла" in query["message"][0]
    assert runtime_values["TELEGRAM_BOT_TOKEN"] == "123456:BAD"
    assert runtime_values["PUBLIC_BASE_URL"] == "https://example.test"
    assert runtime_values["TELEGRAM_USE_WEBHOOK"] == "true"
    assert env_values == runtime_values
