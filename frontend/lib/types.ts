export type Direction = "BUY_CALL" | "BUY_PUT";
export type SignalState =
  | "WATCHING" | "CANDIDATE" | "TRIGGERED" | "INVALIDATED" | "TARGET_1" | "TARGET_2" | "STOPPED" | "TIME_EXIT" | "EXPIRED";

export interface Check { name: string; passed: boolean; detail: string }
export interface ScoreComponent { name: string; weight: number; fraction: number; points: number; detail: string }
export interface Transition {
  ts: string; from_state: SignalState; to_state: SignalState; reason: string; underlying_price: number | null; premium: number | null;
}
export interface Quote {
  bid: number | null; ask: number | null; ltp: number | null; status: string;
  instrument: { symbol: string; strike: number; expiry: string; option_type: "CE" | "PE"; lot_size: number; tick_size: number };
}
export interface TradePlan {
  direction: Direction; underlying: string; contract: Quote["instrument"] & { id: string }; quote: Quote;
  trigger_type: string; trigger_level: number; entry_zone_underlying: [number, number]; entry_ref_underlying: number;
  invalidation_underlying: number; target1_underlying: number; target2_underlying: number; stop_method: string; target_method: string;
  atr: number; delta_used: number; delta_source: string; entry_premium_assumed: number; premium_stop: number;
  premium_target1: number; premium_target2: number; premium_entry_limit: number; spread_pct: number; lot_size: number; lots: number;
  per_lot_risk: number; per_lot_reward_t1: number; rr_t1: number; rr_t2: number; est_costs_round_trip_per_lot: number;
  time_stop: string; warnings: string[];
}
export interface Signal {
  id: string; underlying: string; direction: Direction; state: SignalState; closed: boolean; created_ts: string; updated_ts: string;
  strategy_version: string; trigger_tf: string; plan: TradePlan; score: number | null; score_components: ScoreComponent[];
  rationale: string[]; checks: Check[]; indicators: Record<string, number | null>; data_sources: string[]; transitions: Transition[];
}
export interface Fill { ts: string; side: "BUY" | "SELL"; lots: number; price: number; reason: string; simulated: boolean }
export interface PaperTrade {
  id: string; signal_id: string; underlying: string; symbol: string; direction: Direction; strike: number; option_type: string;
  expiry: string; lot_size: number; lots: number; lots_open: number; status: "OPEN" | "CLOSED"; entry_ts: string; entry_fill: number;
  fills: Fill[]; premium_stop: number; gross_pnl: number; est_costs: number; net_pnl: number; mfe: number; mae: number;
  exit_reason: string; exit_ts: string | null; mark: number | null; data_label: string; data_status: string;
}
export interface WatchRow {
  symbol: string; ltp: number | null; prev_close: number | null; change_pct: number | null; day_open: number | null; vwap: number | null;
  vwap_relation: "ABOVE" | "BELOW" | null; regime: string; volatility: string; atr_pct: number | null; volume_ratio: number | null;
  last_tick_ts: string | null; tick_age_s: number | null; decision: string; no_trade_reasons: string[]; signal_state: string;
  signal_id: string | null; dropped_out_of_order: number; dropped_duplicates: number;
}
export interface RiskSettings {
  confirmed: boolean; defaults_in_use?: boolean; capital: number; max_risk_per_trade: number; max_daily_loss: number; max_open_positions: number;
  max_trades_per_session: number; max_premium_deployed: number; cooldown_after_losses: number; cooldown_minutes: number;
  trading_cutoff: string; paper_square_off: string; min_reward_risk: number; paper_enabled: boolean;
}
export interface RiskState {
  realized_net: number; unrealized: number; trades_today: number; open_positions: number; consecutive_losses: number;
  cooldown_until: string | null; paused: boolean; pause_reason: string;
}
export interface Alert { ts: string; kind: string; signal_id: string | null; underlying: string | null; message: string }
export interface AppState {
  now: string; tz: string; badge: "PRE-MARKET" | "OPEN" | "LIVE" | "STALE DATA" | "MARKET CLOSED" | "SIMULATION"; phase: string; stale: boolean;
  next_event: { label: string; ts: string; seconds: number } | null;
  data: {
    provider: string; status: string; connected: boolean; authenticated: boolean; transport: string; message: string;
    last_tick_ts: string | null; latency_ms: number | null; missing_credentials: string[]; is_simulated: boolean;
    accept_delayed: boolean; start_error: string | null;
  };
  calendar: { verified: boolean; note: string; open: string | null; close: string | null };
  risk_settings: RiskSettings; risk_state: RiskState;
  strategy: { version: string; trigger_tf: string; htf: string; sensitivity: string };
  watchlist: WatchRow[]; active_signals: Signal[]; signal_count: number; open_trades: PaperTrade[]; alerts: Alert[];
  health_log: { ts: string; kind: string; detail: string }[];
  simulator: { paused?: boolean; speed?: number; seed?: number; virtual_now?: string; sim_date?: string };
  live_orders_enabled: boolean; disclaimer: string;
}
export interface SeriesPoint { t: number; v: number | null }
export interface ChartData {
  symbol: string; timeframe: string; label: string;
  candles: { t: number; o: number; h: number; l: number; c: number; v: number; q: string }[];
  ema9: SeriesPoint[]; ema21: SeriesPoint[]; ema50: SeriesPoint[]; vwap: SeriesPoint[];
  opening_range: { high: number | null; low: number | null; complete: boolean };
  levels: { name: string; price: number }[];
  markers: { t: number; state: SignalState; direction: Direction; signal_id: string; price: number | null }[];
  plans: { signal_id: string; state: SignalState; direction: Direction; active: boolean; entry_lo: number; entry_hi: number;
    invalidation: number; t1: number; t2: number; created_t: number }[];
  forming?: { t: number; o: number; h: number; l: number; c: number; v: number } | null;
  ema_periods: number[];
}
export interface ChainSide {
  id: string; symbol: string; ltp: number | null; bid: number | null; ask: number | null; spread_pct: number | null; volume: number | null;
  oi: number | null; oi_change: number | null; iv: number | null; delta: number | null; greeks_source: string | null;
  lot_size: number; tick_size: number; tradable: boolean; age_s: number; status: string; selected: boolean; preferred: boolean;
}
export interface ChainData {
  available: boolean; reason?: string; underlying: string; expiry: string; expiries: string[]; forward: number; status: string;
  source: string; ts: string; rows: { strike: number; ce: ChainSide | null; pe: ChainSide | null }[]; pcr_in_window: number | null;
  context_note: string;
}
export interface Evaluation {
  underlying: string; ts: string; strategy_version: string; trigger_tf: string; decision: string; direction: Direction | null;
  regime: { regime: string; reasons: string[]; adx: number | null; atr_pct: number | null; rsi: number | null };
  htf_regime: string | null; reasons: string[]; checks: Check[]; score: number | null; score_components: ScoreComponent[];
  indicators: Record<string, number | null>; levels: Record<string, number | null>;
}
export interface Summary {
  trades: number; wins: number; losses: number; win_rate_pct: number | null; avg_win: number | null; avg_loss: number | null;
  expectancy_per_trade: number | null; gross_pnl: number; est_costs: number; net_pnl: number; max_drawdown: number;
  open_trades: number; sample_warning: string;
  setups_generated?: number; setups_taken?: number; setups_skipped?: number; setups_by_final_state?: Record<string, number>;
}
export interface SessionReport {
  date: string; origin: string; data_label: string; strategy_versions: string[]; summary: Summary;
  by_underlying: Record<string, Summary>; by_direction: Record<string, Summary>; by_timeframe: Record<string, Summary>;
  by_strategy_version: Record<string, Summary>; by_regime: Record<string, Summary>; cost_assumptions: Record<string, number>;
  data_quality_incidents: { ts: string; kind: string; detail: string }[]; trades: PaperTrade[]; disclaimer: string;
}
export interface ProviderInfo {
  active: { name: string; status: string; connected: boolean; authenticated: boolean; message: string; missing_credentials: string[]; transport: string };
  start_error: string | null;
  capability_matrix: Record<string, unknown>[];
  setup: Record<string, { name: string; env: string[]; needs: string[]; order_permissions: string }>;
}

export interface SetupStep { id: string; label: string; done: boolean; detail: string }
export interface SetupStatus {
  steps: SetupStep[]; next: string | null; provider: string; connect_url: string | null; kite_message: string | null;
  redirect_url_to_register: string;
}
