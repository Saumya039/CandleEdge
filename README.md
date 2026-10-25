# Stratagy — NSE F&O options-buying workstation

A decision-support workstation for **long-only index/stock options (NSE F&O)**: live-style candle charts, indicators,
explainable BUY CALL / BUY PUT / NO TRADE setups, option-chain and liquidity analysis, a paper-trading engine, journal,
backtester, risk limits and daily reports. The product specification is [`CLAUDE.md`](CLAUDE.md).

> **Safety posture.** This app places **no orders**. There is no order endpoint, the provider interface exposes no order
> API, and `LIVE_ORDERS_ENABLED` is `false` and unused. Paper trading is on by default. Nothing here is investment advice;
> every number labelled *estimated* (Greeks, costs, fills) is a model output, and the setup score is **not a probability**.

## Status at a glance

| Area | State |
| --- | --- |
| Simulator mode (seeded, virtual clock, outage injection) | Works end to end; always labelled **SIMULATED** |
| Paper trading, journal, risk gate, daily report, backtest | Works (backtest runs on synthetic data only) |
| Kite Connect live data adapter (read-only) | Implemented, **untested against the real API** (no credentials were available) |
| Live order placement / automated live trading | **Not implemented, by design** |
| Compliance review (spec release gate) | **Not done** — required before any real-money or redistributed use, see [docs/COMPLIANCE.md](docs/COMPLIANCE.md) |
| Exchange holiday calendar | Not hard-coded. Weekday-only plus a visible warning unless you supply `data/exchange_calendar.json` |

## Quickstart (simulator, no credentials)

Requirements: Python 3.11+, Node 20+.

```bash
# backend (http://localhost:8000)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env          # defaults to PROVIDER=simulator
alembic upgrade head                 # also applied automatically on startup
uvicorn stratagy.app:create_app --factory --port 8000

# frontend (http://localhost:3000), second terminal
cd frontend
npm ci
BACKEND_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. The header shows a SIMULATED badge. Simulator controls let you change speed, pause, jump,
and inject a feed outage to watch stale-data handling. Before any paper trade is sized you must open **Risk & paper
trading** and confirm your limits; they are never assumed.

Docker: `docker compose up --build` starts Postgres, backend and frontend with ports bound to `127.0.0.1`. The compose
file and CI YAML parse, but the images were **not built** in the authoring environment (no Docker daemon).

## Activating genuine live data (Zerodha Kite Connect)

You need a Kite Connect developer app **with a market-data subscription**, and a fresh access token every day:

1. Set `KITE_API_KEY` in `.env`.
2. Log in via the Kite login URL, take the `request_token`, then run
   `KITE_API_SECRET=... python scripts/kite_login.py <request_token>` (the secret is read from the environment only)
   and put the printed token in `KITE_ACCESS_TOKEN`.
3. Set `PROVIDER=kite` and restart. Check **Provider** in the UI: it must show LIVE, or DELAYED / STALE / UNAVAILABLE.

Notes: the adapter polls `/quote` about once a second, builds 1m candles from ticks (never inventing missing minutes),
reconciles against historical candles, and backs off with jitter. Spot indices carry no volume, so the nearest future is
used as the signal instrument. Broker secrets live only in the backend environment, never in the browser. With no
credentials or entitlement the app shows **no data** rather than fabricating prices. Other vendors can be added by
implementing `providers/base.py`.

## Configuration (`.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/stratagy.db` | SQLite by default; use a PostgreSQL URL for production |
| `PROVIDER` | `simulator` | `simulator` or `kite` |
| `WATCHLIST` | `NIFTY,BANKNIFTY` | Underlyings to monitor |
| `SIM_SEED`, `SIM_SPEED` | `7`, `60` | Simulator seed and virtual-clock speed (virtual seconds per real second) |
| `KITE_API_KEY`, `KITE_ACCESS_TOKEN` | empty | Live data credentials (placeholders only in `.env.example`) |
| `LIVE_ORDERS_ENABLED` | `false` | Reserved. Has no effect; no order code exists |
| `CORS_ORIGINS`, `LOG_LEVEL` | | Backend CORS and logging |
| `NEXT_PUBLIC_API_URL` / `BACKEND_URL` | | Frontend API base / dev proxy target |

Holidays and special sessions (for example Muhurat) go in `data/exchange_calendar.json`:
`{"holidays": ["2026-11-08"], "special_sessions": [{"date": "...", "open": "18:15", "close": "19:15"}]}`. Verify dates
against the official NSE circular; the app does not ship them.

## How it works

- **Time**: everything is Asia/Kolkata. Session 09:15–15:40, default new-entry cutoff 15:15, configurable.
- **Data health**: every quote and candle is labelled LIVE / DELAYED / SIMULATED / STALE. Stale, gapped or inconsistent
  data fails closed: signals are suppressed and a prominent warning shows until fresh data returns.
- **Strategy `trend-breakout-1.0.0`** (all parameters in `config.py`, versioned): higher-timeframe confirmation, RSI and
  volume checks, breakout or EMA21 pullback-retest trigger, an anti-chase extension limit, swing-based invalidation with
  an ATR buffer, T1/T2 capped at the next support/resistance, and reward:risk **net of spread, slippage and costs**.
  Regime classifier: trending up/down, range/chop, high volatility, insufficient data (the last two block signals).
- **Contracts**: filtered by spread, volume, OI, delta, quote age and expiry; Black-76 IV and Greeks are labelled estimated.
- **Signals** follow a state machine (watching, candidate, triggered, T1/T2, stopped, time exit, invalidated, expired) with idempotent events.
  Each carries its rationale, gate results and indicator snapshot, so nothing is unexplained. No hindsight leakage:
  indicators use only closed candles and confirmed pivots.
- **Paper engine**: conservative fills (buy at ask plus slippage, sell at bid minus slippage), itemised estimated costs,
  partial exit at T1 with a breakeven stop when lots ≥ 2, time stop and square-off.
- **Risk gate**: confirmation required, daily loss, trade count, open positions, loss-streak cooldown, pause, cutoff.
  These only stop new paper entries.
- Signals are intentionally **rare**. NO TRADE is a normal state.

Layout: `backend/stratagy/` (providers, indicators, pricing, strategy, contracts, risk, paper, engine, journal, reports,
backtest, app), `backend/migrations/`, `backend/tests/`, `frontend/` (Next.js 16 App Router, lightweight-charts, Tailwind),
`scripts/`, `docs/`.

## Checks

```bash
cd backend && ruff check . && mypy stratagy && pytest            # 118 tests
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
cd frontend && npx playwright install chromium && npm run e2e     # 7 browser tests against the simulator
```

CI (`.github/workflows/ci.yml`) runs the same checks.

## Known limitations

- Kite adapter not exercised against the real API; field mappings may need adjustment.
- Backtests use synthetic simulator data; no historical option-chain data is bundled, so results say nothing about real
  performance.
- Costs, slippage and Greeks are estimates; real fills and charges will differ.
- Holiday calendar must be supplied by you.
- Single-user, no authentication: run it on localhost or behind your own access control.
- Docker images unbuilt; compliance review pending. Do not use it for real-money decisions before that review.
