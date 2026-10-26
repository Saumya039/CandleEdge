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
| Exchange holiday calendar | 2026 NSE holiday list shipped (unverified copy, check against the NSE circular); Muhurat session not yet added |

## Easiest start (your own computer)

Install [Python 3.11+](https://www.python.org/downloads/) and [Node.js 20+](https://nodejs.org/), then:

- **Practice mode** (simulated data, nothing to set up): double-click `start.bat` (Windows) or run `./start.sh` (Mac/Linux).
- **Live mode** (Zerodha Kite data): double-click `start-live.bat` (Windows), run `./start-live.sh` (Mac/Linux), or run `python run.py --live`. It asks once for your Kite API key and secret and saves
  them in `.env` on your computer only. In your Kite app settings set the Redirect URL to
  `http://127.0.0.1:8000/api/kite/callback`. Then, once each trading day, open the **Provider** tab and click
  **Connect Kite**. You log in on Kite's own page and the app takes it from there.

- **Every F&O index and stock**: double-click `start-live-all-fno.bat` (or `python run.py --live --all-fno`). The list is read from
  Kite's own instrument master each day, so it always matches what is currently eligible. The first start loads history for each
  one and can take several minutes; the scan then covers all of them from one quote request per second. Untested against the real
  API at that size.

The first run installs and builds everything (a few minutes) and opens `http://localhost:3000`. Press Ctrl+C to stop.
A **What to do now** line at the top tells you in plain words whether to wait, watch a forming setup, or act on one.
The app only reads data and paper-trades. It never places orders.

## Quickstart (manual, simulator, no credentials)

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

## Private live deployment

For a password-protected deployment on your own static-IP server (what Kite requires), see
[docs/DEPLOY.md](docs/DEPLOY.md). A live provider refuses to start without a login (`AUTH_PASSWORD_HASH`, `AUTH_SECRET`).

## Recorded demo (no backend)

A static replay of a seeded simulator session, for trying the UI without running the API. Everything in it is real
output of this app's simulator, recorded by a script, and the page is labelled RECORDED SIMULATION REPLAY.

```bash
cd backend && python ../scripts/record_demo_tape.py 1 ../frontend/public/tape-1.json   # seed 1: bearish day
python ../scripts/record_demo_tape.py 7 ../frontend/public/tape-7.json                  # seed 7: bullish day
cd ../frontend && npm run build:demo && npx serve out                                   # static site in frontend/out
```

Risk, strategy and backtest controls are read-only in the demo. Tapes are generated, not committed.

## Charts and TradingView

The main chart uses TradingView's open-source `lightweight-charts` library, drawing the app's own candles with signal
entry, stop, target and trade markers. A **TradingView reference chart** panel below it embeds TradingView's free
Advanced Chart widget for the same NSE symbol. It is opt-in (nothing loads from TradingView until you click *Load
widget*), uses TradingView's own data (usually delayed for NSE without a TradingView subscription), and is never fed
into signals, paper trades or risk checks. TradingView's licensed Charting Library, which could be driven by this app's
feed, requires a licence from TradingView and is not included.

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

`backend/data/exchange_calendar.json` ships with the 2026 NSE trading-holiday list as published on the NSE site
(copied by the project owner, not independently verified: check it against the official NSE circular). The Muhurat session
on Sun 08-Nov-2026 is **not** included because its timings were not yet notified; add it under `special_sessions` as
`{"date": "2026-11-08", "open": "HH:MM", "close": "HH:MM", "note": "Muhurat"}` once NSE announces them.

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
- Holiday calendar covers 2026 only and is an unverified copy of the NSE list; update it for later years.
- Single-user, no authentication: run it on localhost or behind your own access control.
- Docker images unbuilt; compliance review pending. Do not use it for real-money decisions before that review.
