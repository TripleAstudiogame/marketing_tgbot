# Marketing Telegram Bot

Production-oriented Telegram bot for marketing content plans. It reads an Obsidian vault, asks a cloud LLM through a provider router, renders a branded PDF, and sends the result back to Telegram while keeping one live status message updated.

## What It Does

- Accepts a marketing task in Telegram.
- Searches an Obsidian vault stored on the same PC/server.
- Maintains an Obsidian-based AI memory about prior work, marketer preferences, useful facts, and missing data.
- Builds a structured content plan with strategy, calendar, post texts, CTAs, and visual prompts.
- Renders a polished PDF.
- Sends the PDF to Telegram.
- Shows progress in one editable Telegram message, then deletes it before the final answer.
- Provides a browser admin panel for settings, jobs, knowledge search, and reindexing.

## Stack

- Python, FastAPI, aiogram.
- SQLite by default, with `DATABASE_URL` ready for another SQLAlchemy async database later.
- Obsidian as Markdown files.
- Free-first LLM provider router: Gemini, Groq, OpenRouter, local fallback.
- Playwright Chromium for PDF rendering.

## Quick Start On Windows Server 2019

1. Install Python 3.11+ and Git.
2. Copy `.env.example` to `.env`.
3. Fill at least:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
OBSIDIAN_VAULT_PATH=C:\Obsidian\MarketingVault
ADMIN_PASSWORD=strong-password
GEMINI_API_KEY=optional-but-recommended
```

4. Run setup:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

5. Start local all-in-one mode by double-clicking:

```text
START_LOCAL.bat
```

It starts the server, waits for `/health`, and opens the visual setup page automatically.

Or start manually:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\run_local_all.ps1
```

6. Open admin panel:

```text
http://127.0.0.1:8000/admin
```

Use the username/password from `.env`.

For a guided visual setup, open:

```text
http://127.0.0.1:8000/admin/setup
```

The Setup screen lets you connect Telegram, choose/create the Obsidian vault, add AI API keys, test providers, initialize AI Memory, and reindex knowledge.

## Local vs Server Modes

### Local / Same Server With Obsidian

Use polling mode. It does not require a public domain:

```powershell
.\.venv\Scripts\python.exe -m app.cli all
```

This starts:

- FastAPI admin panel.
- Telegram long polling.
- Job worker.

### Webhook / Public Server

Use this when the server has HTTPS and a public URL:

```env
TELEGRAM_USE_WEBHOOK=true
PUBLIC_BASE_URL=https://your-domain.com
RUN_WORKER_IN_WEB=true
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m app.cli web
```

The webhook URL will be:

```text
https://your-domain.com/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>
```

## Obsidian Vault Layout

Recommended:

```text
MarketingVault/
  00_Brand/
    brand.md
    tone_of_voice.md
    offers.md
  01_Audience/
    personas.md
    pains.md
    objections.md
  02_Content/
    hooks.md
    examples.md
  03_Competitors/
    competitor_1.md
  04_Products/
    product_cards.md
  05_Reports/
    generated_plans/
```

The bot reads Markdown directly. You can edit notes in Obsidian, then click **Reindex Knowledge** in the admin panel.

## Admin Panel

Routes:

- `/admin` dashboard.
- `/admin/settings` runtime settings.
- `/admin/knowledge` search and reindex Obsidian vault.
- `/admin/memory` view and initialize AI memory notes.
- `/admin/jobs` generated report jobs.
- `/health` health check.

## AI Memory

The bot has a durable memory layer inside Obsidian. After a task is completed, the AI runs a separate memory extraction step and decides whether something is worth saving for future tasks.

Default folder:

```text
MarketingVault/
  06_AI_Memory/
    _index.md
    marketer_profile.md
    facts.md
    followups.md
    01_Work_Log/
    02_Session_Notes/
```

What it saves:

- marketer preferences and working style;
- durable brand, audience, offer, and positioning facts;
- summaries of completed work;
- missing data and future questions.

What it should not save:

- one-off reasoning;
- passwords, tokens, API keys, and secrets;
- sensitive personal data unless explicitly requested.

Memory settings:

```env
AI_MEMORY_ENABLED=true
AI_MEMORY_DIR=06_AI_Memory
AI_MEMORY_MIN_IMPORTANCE=2
AI_MEMORY_AUTO_REINDEX=true
```

When `AI_MEMORY_AUTO_REINDEX=true`, new memory notes are indexed immediately, so the next Telegram task can use them without manual reindexing.

## AI Providers

Provider order is controlled by:

```env
AI_PROVIDER_ORDER=gemini,groq,openrouter,local
```

If a provider has no key or fails, the router tries the next one. The `local` provider is a deterministic fallback so the bot remains testable without paid APIs.

## PDF Rendering

PDF generation uses Playwright Chromium. The setup script installs the browser:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Generated files are saved in `reports/` and optionally mirrored into:

```text
<ObsidianVault>/05_Reports/generated_plans/
```

## Production Notes

- Keep `.env` private.
- Restrict `TELEGRAM_ALLOWED_USER_IDS` in production.
- Use a strong `ADMIN_PASSWORD`.
- Use HTTPS for webhook mode.
- Run behind Caddy, IIS reverse proxy, Nginx, or a tunnel if exposing the admin panel.
- Back up the Obsidian vault and `data/app.db`.
