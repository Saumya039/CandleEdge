import type { AppState, Signal, WatchRow } from "@/lib/types";

export const watchRow = (o: Partial<WatchRow> = {}): WatchRow => ({
  symbol: "NIFTY", ltp: 24512.35, prev_close: 24400, change_pct: 0.46, day_open: 24420, vwap: 24480, vwap_relation: "ABOVE",
  regime: "TRENDING_UP", volatility: "NORMAL", atr_pct: 0.12, volume_ratio: 1.3, last_tick_ts: "2026-10-23T10:00:00+05:30", tick_age_s: 2,
  decision: "NO_TRADE", no_trade_reasons: ["Trend present but no trigger"], signal_state: "NO_TRADE", signal_id: null,
  dropped_out_of_order: 0, dropped_duplicates: 0, ...o,
});

export const appState = (o: Partial<AppState> = {}): AppState => ({
  now: "2026-10-23T10:00:05+05:30", tz: "Asia/Kolkata", badge: "SIMULATION", phase: "TRADING", stale: false, next_event: null,
  data: {
    provider: "simulator", status: "SIMULATED", connected: true, authenticated: true, transport: "in-process (synthetic)", message: "",
    last_tick_ts: "2026-10-23T10:00:03+05:30", latency_ms: 0, missing_credentials: [], is_simulated: true, accept_delayed: false, start_error: null,
  },
  calendar: { verified: false, note: "Calendar file not configured", open: null, close: null },
  risk_settings: {
    confirmed: true, capital: 500000, max_risk_per_trade: 5000, max_daily_loss: 15000, max_open_positions: 1, max_trades_per_session: 4,
    max_premium_deployed: 100000, cooldown_after_losses: 2, cooldown_minutes: 30, trading_cutoff: "15:15:00", paper_square_off: "15:25:00",
    min_reward_risk: 1.5, paper_enabled: true,
  },
  risk_state: { realized_net: 0, unrealized: 0, trades_today: 0, open_positions: 0, consecutive_losses: 0, cooldown_until: null, paused: false, pause_reason: "" },
  strategy: { version: "trend-breakout-1.0.0", trigger_tf: "5m", htf: "15m", sensitivity: "standard" },
  watchlist: [watchRow(), watchRow({ symbol: "BANKNIFTY", ltp: null, change_pct: null, vwap_relation: null, atr_pct: null })],
  active_signals: [], signal_count: 0, open_trades: [], alerts: [], health_log: [], simulator: { speed: 60, seed: 5, sim_date: "2026-10-23", virtual_now: "2026-10-23T10:00:05+05:30" },
  live_orders_enabled: false, disclaimer: "Not investment advice.", ...o,
});

export const signal = (o: Partial<Signal> = {}): Signal => ({
  id: "sig-1", underlying: "NIFTY", direction: "BUY_CALL", state: "CANDIDATE", closed: false, created_ts: "2026-10-23T10:00:00+05:30",
  updated_ts: "2026-10-23T10:00:00+05:30", strategy_version: "trend-breakout-1.0.0", trigger_tf: "5m", score: 71.4,
  score_components: [{ name: "trend_strength", weight: 25, fraction: 0.8, points: 20, detail: "ADX 28" }],
  rationale: ["Regime TRENDING_UP on 5m", "BREAKOUT of 24500"], checks: [], indicators: { atr: 22.5 }, data_sources: ["simulator:SIMULATED"],
  transitions: [{ ts: "2026-10-23T10:00:00+05:30", from_state: "WATCHING", to_state: "CANDIDATE", reason: "Setup conditions satisfied", underlying_price: null, premium: null }],
  plan: {
    direction: "BUY_CALL", underlying: "NIFTY",
    contract: { id: "SIM:X", symbol: "NIFTY30OCT2624500CE", strike: 24500, expiry: "2026-10-30", option_type: "CE", lot_size: 75, tick_size: 0.05 },
    quote: { bid: 150, ask: 151, ltp: 150.5, status: "SIMULATED", instrument: { symbol: "x", strike: 24500, expiry: "2026-10-30", option_type: "CE", lot_size: 75, tick_size: 0.05 } },
    trigger_type: "BREAKOUT", trigger_level: 24500, entry_zone_underlying: [24500, 24511], entry_ref_underlying: 24511, invalidation_underlying: 24460,
    target1_underlying: 24611, target2_underlying: 24700, stop_method: "pivot 24470 - 0.25 ATR", target_method: "2.5R / 4R", atr: 22, delta_used: 0.52,
    delta_source: "estimated", entry_premium_assumed: 151.5, premium_stop: 130, premium_target1: 203, premium_target2: 240, premium_entry_limit: 157,
    spread_pct: 0.7, lot_size: 75, lots: 2, per_lot_risk: 1700, per_lot_reward_t1: 3900, rr_t1: 2.3, rr_t2: 3.9, est_costs_round_trip_per_lot: 90,
    time_stop: "2026-10-23T11:00:00+05:30", warnings: ["SIMULATED data: no real market, no real fills"],
  },
  ...o,
});
