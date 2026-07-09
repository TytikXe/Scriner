# Crypto Screener

Crypto market screener with a Next.js interface, FastAPI backend, Cloudflare
Worker deployment target, and a Telegram bot for Binance Futures alerts.

## Repository structure

```text
apps/
  api/   FastAPI REST/WebSocket API and tests
  bot/   Telegram formation scanner, chart renderer, and tests
  web/   Next.js frontend
worker.ts       Cloudflare Worker API and static asset entrypoint
wrangler.toml   Cloudflare Workers configuration
```

The application provides screener tables, filters, sorting, watchlists, alerts,
formation/density/level detectors, and an optional OpenAI-compatible analysis
layer. Without an AI API key, the backend uses its deterministic local analyzer.

## Requirements

- Node.js 20+ and npm
- Python 3.11+
- A Telegram bot token only if the alert bot is used

## Local development

### API

```powershell
cd apps\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`. OpenAPI documentation is at
`http://localhost:8000/docs`.

### Web interface

In another terminal:

```powershell
Copy-Item apps\web\.env.example apps\web\.env.local
npm install
npm run dev:web
```

The web interface is available at `http://localhost:3000`.

### Telegram bot

```powershell
cd apps\bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Set TELEGRAM_BOT_TOKEN in .env
python -m formation_bot.main
```

Bot commands and scanner logic are documented in
[`apps/bot/README.md`](apps/bot/README.md).

## Tests

```powershell
python -m pytest apps\api\tests -q
$env:PYTHONPATH="apps\bot"
python -m pytest apps\bot\tests -q
npm run build:web
```

Some reference tests use the public Binance API and are skipped unless their
documented environment flag is enabled.

## Configuration and secrets

Copy the relevant `.env.example` file and keep real values only in local `.env`
files:

- `apps/api/.env.example` — API, storage, and optional AI settings;
- `apps/web/.env.example` — public API and WebSocket URLs;
- `apps/bot/.env.example` — Telegram token and scanner settings.

Local `.env` files, databases, logs, build output, caches, and local tool state
are excluded from Git. Never commit tokens or API keys.

## Giving this project to an AI assistant

Share the GitHub repository URL and ask the assistant to inspect the repository
before answering. Include the exact goal and relevant component, for example:

> Analyze the Telegram scanner in `apps/bot`, find why duplicate alerts can be
> sent, and cite the affected files and functions.

For a private repository, the AI service must have GitHub access granted by the
repository owner. If it cannot read private repositories, provide a source
archive generated from a clean commit instead of sharing secrets.
