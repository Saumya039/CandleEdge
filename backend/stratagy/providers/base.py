"""Provider adapter interface (mirrors the minimum interface in CLAUDE.md section 6).

There is deliberately NO order-placement interface anywhere in this package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from ..models import (
    Candle,
    Instrument,
    MarketSession,
    OptionChainSnapshot,
    ProviderHealth,
    Tick,
    Timeframe,
)

TickCallback = Callable[[Tick], None]


class SubscriptionHandle(Protocol):
    def cancel(self) -> None: ...


class _Handle:
    def __init__(self, cancel: Callable[[], None]):
        self._cancel = cancel

    def cancel(self) -> None:
        self._cancel()


class Capabilities(BaseModel):
    live_ticks: bool = False
    historical_ohlc: bool = False
    option_chain: bool = False
    instrument_master: bool = False
    open_interest: bool = False
    provider_greeks: bool = False
    index_volume: bool = False
    requires_auth: bool = True
    rate_limit_note: str = ""
    order_api: bool = False  # always False: no order interface exists in this project


class UnderlyingSpec(BaseModel):
    symbol: str  # e.g. NIFTY
    signal_instrument: Instrument  # instrument whose candles drive signals
    name: str = ""


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    """Missing credentials / entitlements. Message is safe to show in the UI."""

    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = missing or []


class MarketDataProvider(ABC):
    name: str
    capabilities: Capabilities

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def get_instruments(self) -> list[Instrument]: ...

    @abstractmethod
    def underlyings(self) -> list[UnderlyingSpec]: ...

    @abstractmethod
    async def get_historical_candles(
        self, instrument_id: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]: ...

    @abstractmethod
    async def subscribe_ticks(self, instrument_ids: list[str], on_tick: TickCallback) -> SubscriptionHandle: ...

    @abstractmethod
    async def get_option_chain(self, underlying: str, expiry: date | None = None) -> OptionChainSnapshot: ...

    @abstractmethod
    async def get_market_session(self, d: date) -> MarketSession: ...

    @abstractmethod
    def get_health(self) -> ProviderHealth: ...

    @abstractmethod
    def now(self) -> datetime:
        """Provider-aware wall clock in IST (virtual clock for the simulator)."""
