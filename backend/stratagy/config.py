"""Centralised, versioned configuration. No strategy magic numbers live outside this module."""

from __future__ import annotations

from datetime import time
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Timeframe


class StrategyParams(BaseModel):
    """Parameter set for the rule-based strategy. Bump `version` whenever any value changes."""

    version: str = "trend-breakout-1.0.0"
    trigger_tf: Timeframe = "5m"
    htf: Timeframe = "15m"

    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    adx_period: int = 14
    adx_min_trend: float = 20.0
    high_vol_atr_pct: float = 0.35  # ATR as % of price on trigger tf above which regime=HIGH_VOLATILITY
    min_bars: int = 60  # trigger-tf closed bars (incl. prior-day history) needed before any signal
    or_minutes: int = 15  # opening-range duration

    breakout_lookback: int = 10
    rsi_long_min: float = 55.0
    rsi_long_max: float = 80.0
    rsi_short_min: float = 20.0
    rsi_short_max: float = 45.0
    require_volume: bool = True
    volume_lookback: int = 20
    volume_mult_min: float = 0.9
    max_extension_atr: float = 1.5  # do not chase: close further than this from EMA fast => no trade

    swing_left: int = 2
    swing_right: int = 2
    swing_lookback: int = 40
    stop_atr_buffer: float = 0.25
    min_stop_atr: float = 0.5
    max_stop_atr: float = 3.0
    t1_r: float = 2.5
    t2_r: float = 4.0
    min_rr: float = 1.5  # net of spread/slippage/costs, evaluated on Target 1 in premium terms
    entry_zone_atr: float = 0.5
    candidate_ttl_bars: int = 3
    time_stop_bars: int = 12
    cooldown_bars: int = 6  # per underlying+direction, after any terminal state

    score_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "trend_strength": 25.0,
            "htf_alignment": 15.0,
            "vwap_ema_structure": 15.0,
            "momentum": 10.0,
            "volume": 10.0,
            "room_and_rr": 15.0,
            "liquidity": 10.0,
        }
    )


class ContractParams(BaseModel):
    min_days_to_expiry: int = 1
    max_spread_pct: float = 3.0
    min_volume: int = 500
    min_oi: int = 5000
    delta_min: float = 0.40
    delta_max: float = 0.70
    delta_target: float = 0.55
    max_quote_age_s: float = 10.0


class CostModel(BaseModel):
    """Configurable ESTIMATES for option-buy round trips. Verify against your broker contract note and
    current exchange/government rates before relying on them; none of these are authoritative."""

    brokerage_per_order: float = 20.0
    stt_sell_pct: float = 0.10  # % of sell premium value
    exchange_txn_pct: float = 0.0350  # % of premium turnover (both sides)
    sebi_pct: float = 0.0001
    gst_pct: float = 18.0  # on brokerage + exchange + sebi
    stamp_buy_pct: float = 0.003
    slippage_ticks: float = 2.0  # per side, in option ticks
    slippage_pct: float = 0.25  # per side, % of premium; the larger of the two applies


class RiskSettings(BaseModel):
    """User risk settings. Sizing is refused until `confirmed` is true (explicit user confirmation)."""

    confirmed: bool = False
    capital: float = 500_000.0
    max_risk_per_trade: float = 5_000.0
    max_daily_loss: float = 15_000.0
    max_open_positions: int = 1
    max_trades_per_session: int = 4
    max_premium_deployed: float = 100_000.0
    cooldown_after_losses: int = 2
    cooldown_minutes: int = 30
    trading_cutoff: time = time(15, 15)
    paper_square_off: time = time(15, 25)
    min_reward_risk: float = 1.5
    paper_enabled: bool = True


class DataHealthParams(BaseModel):
    stale_after_s: float = 5.0  # underlying tick age beyond which the feed is STALE
    max_clock_skew_s: float = 30.0  # |local clock - exchange timestamp|
    accept_delayed: bool = False  # explicit user acceptance of DELAYED data
    gap_check_bars: int = 6


class SessionConfig(BaseModel):
    pre_open: time = time(9, 0)
    open: time = time(9, 15)
    close: time = time(15, 40)
    calendar_path: str = "data/exchange_calendar.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/stratagy.db"
    provider: str = "simulator"  # simulator | kite
    watchlist: str = "NIFTY,BANKNIFTY"
    sim_seed: int = 7
    sim_date: str = ""  # YYYY-MM-DD to pin the simulated session date (default: latest weekday)
    sim_speed: float = 60.0  # virtual seconds per real second
    kite_api_key: str = ""
    kite_access_token: str = ""
    # Live order placement is not implemented anywhere in this codebase. This flag exists so that the
    # setting is visibly OFF and is asserted by tests; turning it on does nothing.
    live_orders_enabled: bool = False
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    @property
    def calendar_file(self) -> Path:
        return Path(SessionConfig().calendar_path)
