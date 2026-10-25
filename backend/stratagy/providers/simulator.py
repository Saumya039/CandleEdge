"""SIMULATED market-data provider.

Everything produced here is synthetic (seeded random walk with regime switching, Black-76 option prices with an
invented smile, invented volume/OI) and is labelled DataStatus.SIMULATED everywhere. It exists so the whole
workstation can be exercised without a licensed feed. It must never be presented as live data."""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .. import pricing
from ..candles import resample
from ..models import (
    IST,
    Candle,
    DataStatus,
    Instrument,
    InstrumentKind,
    MarketSession,
    OptionChainRow,
    OptionChainSnapshot,
    OptionQuote,
    OptionType,
    ProviderHealth,
    Tick,
    Timeframe,
)
from ..sessions import ExchangeCalendar
from .base import (
    Capabilities,
    MarketDataProvider,
    SubscriptionHandle,
    TickCallback,
    UnderlyingSpec,
    _Handle,
)

TICK_OFFSETS = tuple(range(1, 60, 3))  # one synthetic tick every 3 seconds
SESSION_MINUTES = 385  # 09:15 .. 15:39 inclusive


@dataclass
class SimUnderlying:
    symbol: str
    start_price: float
    strike_step: float
    lot_size: int  # synthetic: NOT a real contract specification
    base_iv: float
    sigma_min: float  # per-minute return std-dev (fraction)
    base_volume: int


DEFAULT_UNDERLYINGS = [
    SimUnderlying("NIFTY", 24500.0, 50.0, 75, 0.14, 0.00045, 90_000),
    SimUnderlying("BANKNIFTY", 53000.0, 100.0, 30, 0.17, 0.00055, 40_000),
]


def _crc(*parts: object) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def _prev_weekdays(d: date, n: int) -> list[date]:
    out: list[date] = []
    cur = d
    while len(out) < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return sorted(out)


def _generate_day(rng: random.Random, u: SimUnderlying, open_price: float,
                  drift_range: tuple[float, float] = (0.3, 0.6)) -> list[list[tuple[float, int]]]:
    """Per minute: list of (price, tick_qty) for each tick offset. Regime-switching drift/vol."""
    minutes: list[list[tuple[float, int]]] = []
    p = open_price
    anchor = open_price
    remaining = 0
    mode, drift, vmult = "range", 0.0, 1.0
    for m in range(SESSION_MINUTES):
        if remaining <= 0:
            remaining = rng.randint(25, 70)
            mode = rng.choices(["up", "down", "range"], weights=[0.38, 0.38, 0.24])[0]
            vmult = rng.uniform(0.8, 1.5)
            drift = {"up": 1, "down": -1, "range": 0}[mode] * rng.uniform(*drift_range) * u.sigma_min
            anchor = p
        remaining -= 1
        # U-shaped intraday activity profile
        x = m / (SESSION_MINUTES - 1)
        profile = 1.0 + 1.2 * (1 - 4 * x * (1 - x)) ** 2
        base_ret = drift + (-0.04 * (p - anchor) / anchor if mode == "range" else 0.0)
        ticks: list[tuple[float, int]] = []
        mvol = u.base_volume * profile * rng.uniform(0.6, 1.4)
        for _ in TICK_OFFSETS:
            z = rng.gauss(0, 1)
            r = base_ret / len(TICK_OFFSETS) + u.sigma_min * vmult * z / math.sqrt(len(TICK_OFFSETS))
            p = max(p * (1 + r), 1.0)
            surge = 1.0 + 0.5 * min(abs(z), 3.0) * (1.4 if mode != "range" else 0.7)
            ticks.append((p, int(mvol / len(TICK_OFFSETS) * surge)))
        minutes.append(ticks)
    return minutes


class SimulatorProvider(MarketDataProvider):
    name = "simulator"
    capabilities = Capabilities(
        live_ticks=False, historical_ohlc=True, option_chain=True, instrument_master=True, open_interest=True,
        provider_greeks=False, index_volume=True, requires_auth=False,
        rate_limit_note="Synthetic data; no external limits.",
    )

    def __init__(
        self,
        seed: int = 7,
        sim_date: date | None = None,
        start_time: time = time(9, 0),
        underlyings: list[SimUnderlying] | None = None,
        history_days: int = 3,
        calendar: ExchangeCalendar | None = None,
    ):
        self.seed = seed
        self.u = underlyings or DEFAULT_UNDERLYINGS
        today = datetime.now(IST).date()
        d = sim_date or today
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        self.sim_date = d
        self.start_time = start_time
        self.history_days = history_days
        self.calendar = calendar or ExchangeCalendar()
        self._now = datetime.combine(d, start_time, IST)
        self._callbacks: dict[int, tuple[set[str], TickCallback]] = {}
        self._next_cb = 0
        self._connected = False
        self.outage_until: datetime | None = None
        self.paused = False
        self._last_tick_ts: datetime | None = None
        self._last_price: dict[str, float] = {}
        self._cum_vol: dict[str, int] = {}
        self._cursor = 0  # index of next scheduled tick (minute*len(offsets)+k)
        self._offsets = TICK_OFFSETS
        self._n_minutes = SESSION_MINUTES
        self._build()

    # ---- generation -------------------------------------------------------------------------------
    def _build(self) -> None:
        self._index_inst: dict[str, Instrument] = {}
        self._history: dict[str, list[Candle]] = {}
        self._today: dict[str, list[list[tuple[float, int]]]] = {}
        for u in self.u:
            inst = Instrument(
                id=f"SIM:{u.symbol}", exchange="SIM", symbol=u.symbol, underlying=u.symbol,
                kind=InstrumentKind.INDEX, lot_size=u.lot_size, tick_size=0.05,
            )
            self._index_inst[u.symbol] = inst
            price = u.start_price
            hist: list[Candle] = []
            for d in _prev_weekdays(self.sim_date, self.history_days):
                rng = random.Random(_crc(self.seed, u.symbol, d.isoformat()))
                day = _generate_day(rng, u, price, (0.1, 0.3))  # calmer history: indicator warm-up only
                hist.extend(self._to_candles(inst.id, d, day))
                price = day[-1][-1][0]
            rng = random.Random(_crc(self.seed, u.symbol, self.sim_date.isoformat()))
            gap = rng.gauss(0, 0.002)
            self._history[u.symbol] = hist
            self._today[u.symbol] = _generate_day(rng, u, price * (1 + gap))
        self.expiries = [self.sim_date, self.sim_date + timedelta(days=3), self.sim_date + timedelta(days=10)]

    def _to_candles(self, inst_id: str, d: date, day: list[list[tuple[float, int]]]) -> list[Candle]:
        out: list[Candle] = []
        start = datetime.combine(d, time(9, 15), IST)
        for m, ticks in enumerate(day):
            prices = [t[0] for t in ticks]
            out.append(
                Candle(
                    instrument_id=inst_id, timeframe="1m", ts=start + timedelta(minutes=m), open=prices[0],
                    high=max(prices), low=min(prices), close=prices[-1], volume=float(sum(t[1] for t in ticks)),
                    source="SIMULATED",
                )
            )
        return out

    def restart(self, seed: int | None = None) -> None:
        if seed is not None:
            self.seed = seed
        self._now = datetime.combine(self.sim_date, self.start_time, IST)
        self._cursor = 0
        self._last_tick_ts = None
        self._last_price.clear()
        self._cum_vol.clear()
        self.outage_until = None
        self._build()

    # ---- provider API -----------------------------------------------------------------------------
    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    def now(self) -> datetime:
        return self._now

    def underlyings(self) -> list[UnderlyingSpec]:
        return [UnderlyingSpec(symbol=u.symbol, signal_instrument=self._index_inst[u.symbol], name=f"{u.symbol} (SIMULATED)")
                for u in self.u]

    async def get_instruments(self) -> list[Instrument]:
        return list(self._index_inst.values())

    def _spec(self, symbol: str) -> SimUnderlying:
        return next(u for u in self.u if u.symbol == symbol)

    async def get_historical_candles(
        self, instrument_id: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        sym = instrument_id.split(":", 1)[1]
        if sym not in self._history:
            return []
        end = min(end, self._now)  # never return the future
        # prior days only: today's candles are built from ticks by the engine
        c1 = [c for c in self._history[sym] if start <= c.ts and c.ts + timedelta(minutes=1) <= end]
        return resample(c1, timeframe)

    async def subscribe_ticks(self, instrument_ids: list[str], on_tick: TickCallback) -> SubscriptionHandle:
        self._next_cb += 1
        cid = self._next_cb
        self._callbacks[cid] = (set(instrument_ids), on_tick)

        def cancel() -> None:
            self._callbacks.pop(cid, None)

        return _Handle(cancel)

    async def get_market_session(self, d: date) -> MarketSession:
        s = self.calendar.session_for(d)
        if d == self.sim_date:  # the simulated day is always a trading day
            return MarketSession(date=d, open=datetime.combine(d, time(9, 15), IST),
                                 close=datetime.combine(d, time(15, 40), IST), is_trading_day=True,
                                 note="SIMULATED session", calendar_verified=False)
        return s

    def get_health(self) -> ProviderHealth:
        in_outage = self.outage_until is not None and self._now < self.outage_until
        return ProviderHealth(
            name="simulator", status=DataStatus.SIMULATED, connected=self._connected and not in_outage,
            authenticated=True, last_tick_ts=self._last_tick_ts, last_received_ts=self._last_tick_ts,
            latency_ms=0.0, transport="in-process (synthetic)",
            message="SIMULATED feed outage (fault injection)" if in_outage else
            "SIMULATED data: seeded synthetic prices. Not market data.",
        )

    # ---- virtual clock ----------------------------------------------------------------------------
    def inject_outage(self, seconds: float) -> None:
        self.outage_until = self._now + timedelta(seconds=seconds)

    def advance(self, seconds: float) -> list[Tick]:
        """Advance the virtual clock; emit scheduled ticks (except during an injected outage)."""
        target = self._now + timedelta(seconds=seconds)
        emitted: list[Tick] = []
        open_dt = datetime.combine(self.sim_date, time(9, 15), IST)
        n_off = len(self._offsets)
        total = self._n_minutes * n_off
        while self._cursor < total:
            minute, k = divmod(self._cursor, n_off)
            ts = open_dt + timedelta(minutes=minute, seconds=self._offsets[k])
            if ts > target:
                break
            self._cursor += 1
            in_outage = self.outage_until is not None and ts < self.outage_until
            for u in self.u:
                price, qty = self._today[u.symbol][minute][k]
                iid = f"SIM:{u.symbol}"
                self._last_price[u.symbol] = price
                if in_outage:
                    continue
                self._cum_vol[iid] = self._cum_vol.get(iid, 0) + qty
                tick = Tick(instrument_id=iid, ltp=round(price, 2), qty=qty, volume=self._cum_vol[iid],
                            exchange_ts=ts, received_ts=ts)
                emitted.append(tick)
        self._now = target
        for tick in emitted:
            self._last_tick_ts = tick.exchange_ts
            for ids, cb in list(self._callbacks.values()):
                if tick.instrument_id in ids:
                    cb(tick)
        return emitted

    # ---- option chain -----------------------------------------------------------------------------
    async def get_option_chain(self, underlying: str, expiry: date | None = None) -> OptionChainSnapshot:
        u = self._spec(underlying)
        if underlying not in self._last_price:
            raise RuntimeError("No simulated tick yet: option chain unavailable before the first tick.")
        f = self._last_price[underlying]
        now = self._now
        exp = expiry or self.expiries[1]
        exp_dt = datetime.combine(exp, time(15, 30), IST)
        t = pricing.year_fraction(now, exp_dt)
        atm = round(f / u.strike_step) * u.strike_step
        minute_idx = int((now - datetime.combine(self.sim_date, time(9, 15), IST)).total_seconds() // 60)
        rows: list[OptionChainRow] = []
        for i in range(-12, 13):
            k = atm + i * u.strike_step
            row = OptionChainRow(strike=k)
            for kind in (OptionType.CE, OptionType.PE):
                row_q = self._quote(u, f, k, kind, exp, t, now, minute_idx)
                if kind == OptionType.CE:
                    row.ce = row_q
                else:
                    row.pe = row_q
            rows.append(row)
        return OptionChainSnapshot(
            underlying=underlying, expiry=exp, expiries=list(self.expiries), forward=f, rows=rows, ts=now,
            received_ts=now, status=DataStatus.SIMULATED, source="simulator",
        )

    def _quote(self, u: SimUnderlying, f: float, k: float, kind: OptionType, exp: date, t: float,
               now: datetime, minute_idx: int) -> OptionQuote:
        rng = random.Random(_crc(self.seed, u.symbol, k, kind.value, exp.isoformat(), minute_idx))
        tick = 0.05
        iv = u.base_iv + 0.25 * abs(math.log(k / f)) + (0.02 if exp == self.sim_date else 0.0)
        fair = pricing.price(f, k, t, iv, kind)
        sd = max(iv * math.sqrt(max(t, 1 / 365)), 1e-6)
        mny = abs(math.log(k / f)) / sd
        spread_pct = min(0.004 + 0.012 * mny**1.5, 0.30)
        half = max(tick, fair * spread_pct / 2)
        bid = max(math.floor((fair - half) / tick) * tick, 0.0)
        ask = math.ceil((fair + half) / tick) * tick
        ltp = round(round((fair + rng.uniform(-0.3, 0.3) * half) / tick) * tick, 2)
        liq = math.exp(-0.5 * mny**2)
        elapsed = max(minute_idx, 1)
        volume = int(u.base_volume * 0.4 * liq * (0.7 + rng.random() * 0.6) * min(elapsed, 120) / 20)
        oi = int(u.base_volume * 8 * liq * (0.8 + rng.random() * 0.4))
        inst = Instrument(
            id=f"SIM:{u.symbol}{exp:%y%m%d}{int(k)}{kind.value}", exchange="SIM",
            symbol=f"{u.symbol}{exp:%d%b%y}{int(k)}{kind.value}".upper(), underlying=u.symbol,
            kind=InstrumentKind.OPTION, expiry=exp, strike=k, option_type=kind, lot_size=u.lot_size,
            tick_size=tick,
        )
        g = pricing.greeks(f, k, t, iv, kind)
        return OptionQuote(
            instrument=inst, ltp=ltp if ltp > 0 else None, bid=round(bid, 2) if bid > 0 else None,
            ask=round(ask, 2), volume=volume, oi=oi, oi_change=int(oi * rng.uniform(-0.03, 0.05)), greeks=g,
            ts=now, received_ts=now, status=DataStatus.SIMULATED,
        )
