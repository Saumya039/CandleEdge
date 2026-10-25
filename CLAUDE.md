# CLAUDE.md — Live Indian F&O Options Strategy Workstation

## 1. Product mission

Build a reliable, real-time intraday decision-support application for the Indian stock market, focused on **buying CALL and PUT options** on NSE index and eligible stock derivatives. During the trading session, continuously monitor the selected underlyings and option contracts, interpret the live trend, and display explainable candidate setups with proposed entry zone, stop-loss, targets, invalidation conditions, and live chart annotations.

This is a **trading research and decision-support tool**, not a profit-guarantee system. A setup is a conditional scenario, not a certainty or personalized promise of returns. The default experience is **paper trading / signals only**. Never place a live order automatically. Keep broker order execution out of the MVP; only add a manual, user-confirmed order-ticket integration later, and only after broker and regulatory requirements have been reviewed.

## 2. Non-negotiable rules

1. **No fake live data.** Never label mock, delayed, cached, sample, or replay data as live. Display provider, exchange timestamp, last-received timestamp, and LIVE / DELAYED / SIMULATED / STALE status clearly.
2. **No fabricated signals or price levels.** Every signal, indicator, entry, stop, target, option quote, OI value, IV, Greek, and chart marker must come from real input data and deterministic calculations. If a data field is unavailable, show “Unavailable” and explain that the signal cannot use it.
3. **Fail closed.** When quotes are stale, subscriptions disconnect, instrument mapping is uncertain, the clock is wrong, data is inconsistent, or required indicators cannot be calculated, suppress new signals and show a prominent data-health warning.
4. **No automatic live trading.** No live order placement, modification, cancellation, or position closure in the MVP. Do not store broker secrets in the browser. Do not bypass broker authentication or exchange data-access rules.
5. **Long options only.** This product is for buying calls and puts. Do not create short-option or option-selling strategies.
6. **Explain every recommendation.** For each setup show why it triggered, what would invalidate it, what data was used, strategy version, timeframe, and risk/reward math.
7. **No hindsight leakage.** Signals must be computed only from information available at the signal timestamp. In backtests, do not use future candles, future OI, or future option-chain data.
8. **Current compliance is a release gate.** Before enabling any broker integration beyond market-data viewing, verify current SEBI, NSE/BSE, broker, data licensing, retail API/algo-trading, registration, IP, order tagging, audit-log, and rate-limit requirements from official current sources. Do not claim the app is compliant without review by a qualified compliance professional and the relevant broker/exchange.

## 3. Market session and product scope

- Time zone: `Asia/Kolkata` everywhere in UI, server logic, logs, persisted timestamps, and session logic.
- Standard NSE equity derivatives session is currently listed as **09:15–15:40 IST**, subject to holidays, special sessions, and exchange notices. Do not hard-code market days alone: maintain a configurable exchange calendar and session configuration.
- Before open: validate credentials and data connectivity, refresh instrument master and contract metadata, load enough historical candles to initialize indicators, and show a pre-market status. Do not generate intraday entry signals before the configured opening-range/data-readiness rules are satisfied.
- During session: maintain live feeds and recalculate on closed candles (and on live ticks only where required, e.g. quote/premium monitoring). Support watchlists of liquid index underlyings such as NIFTY and BANKNIFTY plus broker-supported, currently eligible stock derivatives. Do not assume all symbols or expiries are tradable.
- Near close: stop proposing new entries at a configurable cutoff (default 15:15 IST), warn about time decay/liquidity and the approaching derivatives close, and show outstanding paper positions and exit/invalidation alerts. Do not silently carry an intraday strategy into the next session.
- After close: stop session signals, reconcile data, save the signal and paper-trade journal, calculate session stats, and show a review. Never imply an order was executed unless an authenticated broker order update confirms it.
- Respect exchange holidays and special sessions, and show when the live session is not active.

## 4. Main user experience

Build a polished desktop-first trading workstation that is also responsive on tablets and phones. Use a clear dark theme by default, accessible contrast, readable numbers, compact panels, and no visual clutter. Avoid flashy animations that hide price changes.

### A. Live market dashboard

- Session badge and countdown/status: PRE-MARKET, OPEN, LIVE, STALE DATA, MARKET CLOSED, or SIMULATION.
- Current IST time, data-provider status, last tick timestamp, latency/age of data, WebSocket status, and market calendar state.
- Watchlist with underlying LTP, % change, VWAP relation, trend regime, volatility regime, volume condition, and signal state.
- Market overview for selected underlying: current price, day high/low, opening range, previous close, VWAP, and major intraday support/resistance derived from available candles.
- A clear NO TRADE state when confirmation is inadequate; do not force a setup just to keep the screen busy.

### B. Strategy/scan panel

- Continuously scan configured underlyings during the eligible session.
- Rank candidate setups by a transparent setup-quality score; show the score components. Do not call a score a probability of profit unless it is calibrated and validated out of sample.
- Filters: underlying, index/stock, timeframe, signal type (CALL / PUT / NO TRADE), minimum liquidity, minimum reward-to-risk, and expiry selection.
- Settings for risk budget, max trades per session, max daily loss, trading cutoff, opening-range duration, and signal sensitivity. All are user-configurable; do not silently override a user's risk settings.
- Avoid alert spam: deduplicate the same setup, use cooldowns, and alert when a setup materially changes, triggers, invalidates, or exits.

### C. Charts and trade-plan visualization

Use a real interactive candlestick chart (for example, TradingView Lightweight Charts, subject to its current license and use requirements). Never use fabricated candle data in connected/live mode.

Show:
- Underlying candlestick chart with selectable 1m, 3m, 5m, and 15m timeframes, volume, VWAP, EMA 9/21/50, opening-range high/low, and calculated support/resistance.
- Option premium candlestick/line chart for the selected contract, with bid/ask or quote spread when supplied by the provider.
- BUY CALL / BUY PUT candidate marker at the signal time, proposed entry zone, stop-loss line, Target 1 and Target 2 lines, and invalidation level. Show whether the underlying condition or option premium condition triggers each level.
- A synchronized marker/timeline between underlying and option charts when practical.
- Hover crosshair with exact time, OHLC, volume, and indicator values. Chart data must be timezone-consistent and correctly ordered.
- A signal card beside the chart containing: signal status, underlying, contract symbol, expiry, strike, CE/PE, lot size from current instrument metadata, quote status, suggested entry zone, stop loss, targets, estimated reward-to-risk, setup-quality score, rationale, invalidation condition, time stop, and warnings.
- Use distinct visual labels for “candidate”, “triggered”, “invalidated”, “target reached”, and “stopped” in the signal/paper-trade ledger. Do not visually imply a simulated fill is a real fill.

### D. Option chain and contract picker

- Use an authorized broker/vendor API. Display available strikes and expiries, underlying price, CE/PE LTP, bid/ask and spread, volume, open interest, and change in OI only when actually provided and permitted.
- Display implied volatility and Greeks only when obtained from a reliable provider or computed with documented, tested assumptions and sufficient inputs. Label calculated values as estimates; never invent missing IV/Greeks.
- Show expiry, strike, option type, lot size, tick size, and tradability from the current instrument master. Do not hard-code lot sizes, expiries, or symbol formats.
- Contract selection should prefer liquid contracts and avoid extremely wide spreads, very low volume, stale quotes, and near-expiry contracts with unreliable prices. Make the criteria visible and configurable.
- Do not assume PCR or OI alone predicts direction. Show these as contextual measures, not standalone buy/sell triggers.

### E. Risk and paper-trading panel

- Paper trading is ON by default. It simulates fills using a documented conservative fill model, including spread/slippage assumptions; it never sends broker orders.
- Let the user configure capital, max risk per trade, max total daily loss, max open paper positions, max trades/session, and max premium deployed. Require explicit values/confirmation before calculating position size.
- Position sizing must respect option lot size and user's configured risk budget. If one lot exceeds the risk budget, show “No trade: minimum lot exceeds risk budget” rather than violating the limit.
- Model option premium risk and underlying-based invalidation separately. Premiums can decay, gap, or react nonlinearly; a stop level is not guaranteed to fill at that price.
- Display gross P&L and estimated costs separately. Do not pretend estimated brokerage, STT, exchange charges, GST, stamp duty, or slippage are exact; allow configurable cost assumptions and mark estimates clearly.
- Implement hard application-level safeguards in the signal/paper engine: daily loss limit, trade-count limit, position-count limit, stale-data block, cutoff-time block, cooldown after repeated losses (configurable), and a global pause button. Safeguards should stop new entries; they must not claim to close real brokerage positions.

### F. Journal and review

- Store every generated setup, its inputs/indicator snapshot, strategy version, decision, invalidation, and observed outcome.
- Paper-trade journal: entry/exit timestamps, simulated fills, lots, gross/net estimated P&L, maximum adverse/favorable excursion where data supports it, and reason for exit.
- Daily and historical reports: number of setups, taken/skipped setups, win/loss counts, average win/loss, expectancy, drawdown, fees/slippage assumptions, performance by trend regime/timeframe/strategy version, and data-quality incidents.
- Clearly distinguish backtest, paper-trading, and live-market observation results. Do not present backtest results as a forecast or marketing claim.

## 5. Strategy engine: deterministic, explainable, versioned

Implement a modular strategy engine. Keep indicators and signal rules in tested, independent modules. The first release should use explicit rule-based strategies; an LLM can optionally summarize a signal in plain English, but must never invent prices, override deterministic rules, or submit orders.

### Market regime detection

Classify the current market as one of:
- TRENDING_UP
- TRENDING_DOWN
- RANGE/CHOP
- HIGH_VOLATILITY
- INSUFFICIENT_DATA

Use multiple signals, such as price structure, EMA alignment/slope, VWAP relation, ADX, ATR/realized volatility, volume, and opening-range behavior. Define every calculation and threshold in configuration. Avoid circular indicator calculations and verify indicator values against known test fixtures.

### Candidate BUY CALL conditions (example baseline, parameters configurable)

A candidate may be generated only when the data-quality gate passes and multiple conditions agree, such as:
- Underlying trend and intraday structure are bullish on the trigger timeframe, with confirmation from a higher timeframe where available.
- Price is above VWAP and the selected EMA alignment/slope supports the move, or a documented breakout/retest setup occurs.
- Momentum/volume confirms rather than contradicts the move.
- The setup has enough room to the next resistance level and meets the configured minimum reward-to-risk after conservative slippage/cost assumptions.
- The selected call option is liquid, its quote is fresh, the spread is below a configurable threshold, and the contract metadata is valid.

### Candidate BUY PUT conditions

Use the mirrored bearish logic: lower highs/lower lows or confirmed breakdown/retest, price below VWAP with bearish EMA structure, momentum/volume confirmation, room to the next support, acceptable reward-to-risk, and a liquid, fresh put contract with a valid spread.

### NO TRADE conditions

Do not generate an entry candidate when:
- Trend signals conflict or market regime is RANGE/CHOP without a separately defined range strategy.
- Underlying and option feeds are stale, disconnected, delayed without explicit user acceptance, or missing required fields.
- Required opening range/history has not formed, contract metadata is unresolved, or candle data contains gaps/duplicates.
- Spread, liquidity, volatility, or slippage makes the setup unsuitable according to configurable limits.
- Reward-to-risk falls below the configured threshold, the setup has already moved too far from its entry zone, or the cutoff time has passed.
- The daily risk limit, max trade count, max position count, pause flag, or cooldown blocks new entries.

### Entry, stop, targets, and invalidation

- Compute a proposed entry zone from a documented trigger, such as a confirmed breakout/retest or an option-premium trigger after underlying confirmation. Do not chase if price has moved outside the planned zone.
- Base invalidation primarily on the underlying structure that justified the trade; also show a premium risk-control level for the option. Explain both distinctly.
- Derive stops/targets using tested structural levels and/or ATR-based distances. The selected method, parameters, and source timeframe must be visible and logged.
- Calculate per-lot risk, max loss at the stop assumption, Target 1/2 reward-to-risk, and position size with unit-tested formulas. Include spread and configurable slippage/cost assumptions.
- Require a configurable minimum reward-to-risk before showing a setup as actionable. If no defensible stop/target can be calculated, show “NO TRADE: risk levels unavailable.”
- Add time-based invalidation/exit reminders and a configurable no-new-entry cutoff before market close.
- Signals must transition through a state machine: `WATCHING -> CANDIDATE -> TRIGGERED -> INVALIDATED | TARGET_1 | TARGET_2 | STOPPED | TIME_EXIT | EXPIRED`. Define transitions and idempotency so duplicate ticks cannot create duplicate trades/alerts.
- Version every strategy and parameter set. Store signal snapshots so the user can reconstruct why a signal was shown.

## 6. Data architecture and integrity

### Provider integration

Build an adapter interface so broker/vendor providers can be swapped without changing UI or strategy logic. Create a provider capability matrix for live ticks, OHLC/history, option chain, instruments, OI, Greeks, authentication, rate limits, and order APIs.

- Start with one actual broker/vendor adapter only after selecting a supported provider and checking its current official documentation, pricing, permitted uses, authentication flow, WebSocket limits, market-data entitlements, and terms. If no credentials are configured, run only an explicitly labelled simulator/replay mode.
- Do not scrape exchange webpages or unofficial endpoints for production live data. Use official broker/vendor APIs or properly licensed data.
- Keep all secrets in server-side environment variables or a secure secret store. Never put API secrets or access tokens in frontend bundles, browser local storage, logs, screenshots, or source control.
- Implement authentication refresh/reconnect, exponential backoff with jitter, heartbeat/watchdog, resubscription, rate limiting, clean shutdown, and a visible last-data timestamp.
- Normalize provider data into internal types: `Instrument`, `Tick`, `Candle`, `OptionQuote`, `OptionChainSnapshot`, `MarketSession`, `Signal`, `TradePlan`, and `PaperTrade`.
- Use exchange timestamps when supplied, preserve source timestamps, and separately record receive timestamps. Handle out-of-order ticks and duplicate messages deterministically.
- Build OHLC candles from ticks only when permitted and necessary; otherwise use provider candles. Make candle boundaries consistent and test them. Do not silently fill missing candles with invented prices.
- Persist instrument metadata, candles needed for review, signal snapshots, strategy versions, paper trades, session health events, and audit events. Apply retention rules and avoid storing unnecessary sensitive data.

### Minimum provider interface (adapt as needed)

```ts
interface MarketDataProvider {
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  getInstruments(): Promise<Instrument[]>;
  getHistoricalCandles(instrumentId: string, timeframe: Timeframe, from: Date, to: Date): Promise<Candle[]>;
  subscribeTicks(instrumentIds: string[], onTick: (tick: Tick) => void): Promise<SubscriptionHandle>;
  getOptionChain?(underlyingId: string, expiry?: string): Promise<OptionChainSnapshot>;
  getMarketSession(date: string): Promise<MarketSession>;
  getHealth(): ProviderHealth;
}
```

Provider-specific optional capabilities must be explicit rather than silently substituted with fabricated values. A separate broker-order interface must not be wired into the MVP.

## 7. Suggested implementation stack

Use a maintainable stack unless the repository already has a sound, working stack:

- Frontend: Next.js App Router, React, TypeScript, Tailwind CSS, accessible UI components, a real candlestick chart library, and a small typed API client.
- Backend/data services: Python 3.12 + FastAPI + Pydantic for market/strategy services; pandas/numpy or a tested indicator library for calculations.
- Persistence: PostgreSQL + SQLAlchemy/Alembic migrations.
- Realtime fan-out/cache: Redis Streams or Pub/Sub if needed; keep the first version simple and document why each service exists.
- Testing: pytest for backend/strategy, Vitest/Testing Library for frontend, and Playwright for the critical end-to-end user path.
- Local development: Docker Compose, `.env.example`, migrations, seeded **synthetic** demo data clearly labelled SIMULATED, and documented commands.

Do not introduce unnecessary microservices. If the existing repository uses a different stack, inspect and reuse it when sensible. Keep secrets and broker sessions on the server side. Set up structured logs, request IDs, health endpoints, and safe error messages.

## 8. Suggested domain objects

Design typed schemas and database tables for:
- `UserSettings`: watchlist, timezone, risk limits, preferred timeframes, strategy parameters, notification preferences.
- `Instrument`: provider ID, exchange, symbol, underlying, instrument type, expiry, strike, CE/PE, lot size, tick size, validity dates.
- `Candle`: instrument ID, timeframe, open/high/low/close, volume, timestamp, source/provider, data-quality flag.
- `OptionQuote` / `OptionChainSnapshot`: quote, bid/ask, spread, volume, OI/change in OI, IV/Greeks if available, provider timestamp, data status.
- `Signal`: ID, strategy/version, underlying, option contract, direction, state, timestamp, quality score and components, rationale, invalidation, source snapshot, data quality.
- `TradePlan`: entry zone, premium stop, underlying invalidation, targets, time exit, lot size, suggested quantity, risk/reward calculations, costs/slippage assumptions.
- `PaperTrade`: lifecycle state, entries/exits, simulated fills, quantity/lots, P&L, costs, exit reason, source signal.
- `ProviderHealth` / `AuditEvent`: connection state, latency, stale periods, errors, settings changes, signal transitions, and user actions.

Validate all inputs on server and treat broker/vendor responses as untrusted external data.

## 9. Security, reliability, and privacy

- Authenticated app sessions with secure, HTTP-only, SameSite cookies if accounts are implemented; use CSRF protection where applicable, rate limits, server-side authorization, and secure headers.
- Encrypt secrets/tokens at rest where persisted; rotate/revoke tokens safely; redact secrets in logs. Never ask the user to paste a password, TOTP secret, or API secret into a chat or source file.
- Use least privilege; separate market-data permissions from order permissions. The MVP should not request order permissions when not needed.
- Implement graceful degradation and visible error states. A reconnect must not duplicate subscriptions, signals, alerts, or paper entries.
- Add audit trails for strategy configuration, risk settings, provider connections, signal generation and transitions, and paper-trade events.
- Include data source, delay status, disclaimer, privacy policy placeholder, and a clear kill/pause control. Avoid claiming regulatory approval or guaranteed profits.

## 10. Testing and validation requirements

Write tests before calling the strategy engine reliable. Include:

- Indicator unit tests with known sample data (EMA, VWAP, RSI, ATR, ADX, opening range, swing levels).
- Market-session and holiday tests, including special-session configuration and boundaries around 09:15 and 15:40 IST.
- Timezone/DST-safe timestamp tests (India has no current seasonal DST, but never use server-local time).
- Feed tests: stale ticks, reconnects, duplicate/out-of-order ticks, missing candles, invalid option metadata, rate limits, and provider failure.
- Contract selection tests for expiry, strike, lot size, CE/PE, liquidity, spread, and tradability.
- Strategy tests for bullish, bearish, sideways, contradictory, high-volatility, late-entry, insufficient-data, and risk-limit conditions.
- State-machine/idempotency tests so repeated ticks cannot emit duplicate alerts or entries.
- Risk-sizing tests including a single lot exceeding the configured risk budget.
- Backtesting with no lookahead bias, realistic spread/slippage/cost assumptions, train/test separation where applicable, and clear disclosure when historical option-chain data is unavailable.
- UI/end-to-end tests for no-data state, simulated mode banner, live-feed loss warning, chart markers, settings, pause button, and paper-trade journal.

Do not claim profitability, accuracy, or live readiness based solely on passing unit tests. Add forward paper-trading evaluation and a clear evidence report before considering more ambitious models.

## 11. Delivery plan

Build in phases, keeping the app runnable at every phase:

1. **Repository assessment:** inspect existing files, package managers, tests, and project conventions. Provide a short plan, then implement; do not overwrite working parts without explaining why.
2. **Working UI shell:** dashboard layout, watchlist, live status, underlying chart, option chart, signal card, option chain, settings, journal, and simulated mode banner.
3. **Core data model and simulator:** typed schemas, persistence, synthetic/replay ticks explicitly labelled SIMULATED, candle builder, chart updates, and health indicators.
4. **Strategy engine:** tested indicators, market regime, call/put candidate rules, no-trade filters, entry/stop/target logic, state machine, risk sizing, and explainable scoring.
5. **Real market-data adapter:** implement only after provider and required credentials are configured; check official docs and entitlements. Show “LIVE” only when the feed is authenticated, authorized, current, and healthy.
6. **Paper-trading journal and reporting:** simulated fills, costs/slippage assumptions, session reports, and backtest/replay support.
7. **Hardening:** security review, tests, reconnect/load handling, observability, performance checks, and current regulatory/provider review. Do not activate live order placement as part of this plan.

At the end of each phase, run relevant tests and build/lint/typecheck commands. Fix errors before proceeding. Do not leave TODOs or nonfunctional buttons on critical paths; when a provider credential or licensed feed is missing, implement an explicit, useful setup/error state rather than a fake integration.

## 12. Required developer workflow for Claude Code

- First inspect the entire repository and summarize the actual current stack and existing behavior.
- Create a practical implementation plan based on repository reality. Then start implementing; do not stop after producing a proposal.
- Build vertical slices that run end-to-end, with clear file/module boundaries and typed interfaces.
- Prefer small, testable functions; avoid monolithic components and hidden strategy magic numbers.
- Keep all strategy parameters centralized and versioned; include comments and documentation for formulas and assumptions.
- Add `.env.example` containing names/placeholders only, never real secrets. Document setup, data-provider requirements, simulator mode, tests, and operational limitations in `README.md`.
- After changes, run tests, lint, typecheck, and build where scripts exist. Report actual commands and results; never claim a check passed if it was not run.
- List what is implemented, what still requires user credentials/provider entitlements, and what requires compliance review. Do not claim the software can reliably predict the market.

## 13. Definition of done for the first usable MVP

- The dashboard runs locally and visibly distinguishes simulation from authorized live market data.
- The chart updates from the selected feed/replay and shows candlesticks, indicators, trade-plan levels, and signal markers.
- Candidate CALL/PUT setups include an explainable reason, entry zone, stop, targets, invalidation, risk/reward, contract metadata, timestamp, and data-health status.
- No-trade cases are first-class and appear for conflicting signals, stale feeds, poor liquidity/spread, late entries, or exceeded risk settings.
- Paper trading and journal work without sending broker orders.
- The signal engine is unit-tested; session boundaries, feed failures, and idempotency are tested.
- Setup docs clearly state which credentials, subscriptions, and compliance checks are required for true live use.
- No placeholder values are presented as real prices, no guarantee of profits is made, and there is no automatic live order execution.
