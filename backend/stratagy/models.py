"""Internal, provider-neutral domain types. All datetimes are timezone-aware (Asia/Kolkata)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

IST = ZoneInfo("Asia/Kolkata")

Timeframe = Literal["1m", "3m", "5m", "15m"]
TF_MINUTES: dict[str, int] = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}


class DataStatus(StrEnum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    SIMULATED = "SIMULATED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class InstrumentKind(StrEnum):
    INDEX = "INDEX"
    FUTURE = "FUTURE"
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"


class Instrument(BaseModel):
    id: str
    exchange: str
    symbol: str
    underlying: str
    kind: InstrumentKind
    expiry: date | None = None
    strike: float | None = None
    option_type: OptionType | None = None
    lot_size: int = 1
    tick_size: float = 0.05
    tradable: bool = True


class Tick(BaseModel):
    instrument_id: str
    ltp: float
    qty: int = 0
    volume: int | None = None  # cumulative day volume when the provider supplies it
    bid: float | None = None
    ask: float | None = None
    oi: int | None = None
    exchange_ts: datetime | None = None
    received_ts: datetime


class Candle(BaseModel):
    instrument_id: str
    timeframe: Timeframe
    ts: datetime  # candle START time, IST
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    source: str = "unknown"
    quality: Literal["ok", "gap", "partial"] = "ok"


class Greeks(BaseModel):
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None  # per calendar day
    vega: float | None = None  # per 1 vol point
    iv: float | None = None
    source: Literal["provider", "estimated"] = "estimated"


class OptionQuote(BaseModel):
    instrument: Instrument
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    oi: int | None = None
    oi_change: int | None = None
    greeks: Greeks | None = None
    ts: datetime  # exchange timestamp when supplied
    received_ts: datetime
    status: DataStatus = DataStatus.UNAVAILABLE

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return None

    @property
    def spread(self) -> float | None:
        if self.bid and self.ask and self.bid > 0 and self.ask >= self.bid:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> float | None:
        m, s = self.mid, self.spread
        return None if m is None or s is None else 100.0 * s / m


class OptionChainRow(BaseModel):
    strike: float
    ce: OptionQuote | None = None
    pe: OptionQuote | None = None


class OptionChainSnapshot(BaseModel):
    underlying: str
    expiry: date
    expiries: list[date] = Field(default_factory=list)
    forward: float
    rows: list[OptionChainRow]
    ts: datetime
    received_ts: datetime
    status: DataStatus
    source: str


class MarketSession(BaseModel):
    date: date
    open: datetime | None
    close: datetime | None
    is_trading_day: bool
    note: str = ""
    calendar_verified: bool = False


class ProviderHealth(BaseModel):
    name: str
    status: DataStatus
    connected: bool
    authenticated: bool
    last_tick_ts: datetime | None = None
    last_received_ts: datetime | None = None
    latency_ms: float | None = None
    transport: str = "none"
    message: str = ""
    missing_credentials: list[str] = Field(default_factory=list)


class Direction(StrEnum):
    CALL = "BUY_CALL"
    PUT = "BUY_PUT"


class SignalState(StrEnum):
    WATCHING = "WATCHING"
    CANDIDATE = "CANDIDATE"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    STOPPED = "STOPPED"
    TIME_EXIT = "TIME_EXIT"
    EXPIRED = "EXPIRED"


class Regime(StrEnum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE_CHOP = "RANGE_CHOP"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
