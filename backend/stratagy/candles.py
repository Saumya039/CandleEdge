"""Tick -> 1m candle builder and 1m -> N-minute resampling. Never invents prices for missing minutes."""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import IST, TF_MINUTES, Candle, Tick, Timeframe

SESSION_OPEN_MIN = 9 * 60 + 15  # candle slots are aligned to the 09:15 IST session open


def floor_minute(ts: datetime) -> datetime:
    return ts.astimezone(IST).replace(second=0, microsecond=0)


class CandleBuilder:
    """Builds closed 1m candles from ticks for one instrument.

    Deterministic rules: the minute is taken from the exchange timestamp when supplied (else the receive
    timestamp, counted in `ticks_without_exchange_ts`); ticks older than the newest accepted tick are dropped
    as out-of-order; a tick identical to the previous one (ts, price, cumulative volume) is a duplicate."""

    def __init__(self, instrument_id: str, source: str):
        self.instrument_id = instrument_id
        self.source = source
        self.closed: dict[datetime, Candle] = {}
        self.current: Candle | None = None
        self.last_ts: datetime | None = None
        self._last_key: tuple | None = None
        self._prev_cum: int | None = None
        self._cum_day: object = None
        self.dropped_out_of_order = 0
        self.dropped_duplicates = 0
        self.ticks_without_exchange_ts = 0

    def seed_history(self, candles: list[Candle]) -> None:
        for c in candles:
            self.closed[c.ts] = c

    def on_tick(self, tick: Tick) -> Candle | None:
        """Returns the candle that CLOSED because of this tick (if any)."""
        if tick.exchange_ts is None:
            self.ticks_without_exchange_ts += 1
        ts = (tick.exchange_ts or tick.received_ts).astimezone(IST)
        key = (ts, tick.ltp, tick.volume)
        if self._last_key == key:
            self.dropped_duplicates += 1
            return None
        if self.last_ts is not None and ts < self.last_ts:
            self.dropped_out_of_order += 1
            return None
        self._last_key = key
        self.last_ts = ts

        minute = floor_minute(ts)
        if minute in self.closed and (self.current is None or minute != self.current.ts):
            self.dropped_out_of_order += 1  # minute already finalised (e.g. from history)
            return None

        if self._cum_day != ts.date():
            self._cum_day, self._prev_cum = ts.date(), None
        vol = float(tick.qty)
        if tick.volume is not None:
            vol = 0.0 if self._prev_cum is None else float(max(tick.volume - self._prev_cum, 0))
            self._prev_cum = tick.volume

        closed: Candle | None = None
        if self.current is not None and minute != self.current.ts:
            closed = self.current
            self.closed[closed.ts] = closed
            self.current = None
        if self.current is None:
            self.current = Candle(
                instrument_id=self.instrument_id, timeframe="1m", ts=minute, open=tick.ltp, high=tick.ltp,
                low=tick.ltp, close=tick.ltp, volume=vol, source=self.source,
            )
        else:
            c = self.current
            c.high, c.low, c.close = max(c.high, tick.ltp), min(c.low, tick.ltp), tick.ltp
            c.volume += vol
        return closed

    def closed_list(self) -> list[Candle]:
        return [self.closed[k] for k in sorted(self.closed)]


def _slot(ts: datetime, n: int) -> int:
    mins = ts.hour * 60 + ts.minute - SESSION_OPEN_MIN
    return mins // n


def resample(candles_1m: list[Candle], tf: Timeframe) -> list[Candle]:
    """Aggregate CLOSED 1m candles into `tf` candles aligned to 09:15 IST. A bucket is emitted only when it is
    closed: a later 1m candle exists, or its final minute is present. Buckets with missing minutes carry
    quality='gap' (never silently filled)."""
    n = TF_MINUTES[tf]
    if tf == "1m":
        return list(candles_1m)
    out: list[Candle] = []
    if not candles_1m:
        return out
    last_ts = candles_1m[-1].ts
    buckets: dict[tuple, list[Candle]] = {}
    for c in candles_1m:
        buckets.setdefault((c.ts.date(), _slot(c.ts, n)), []).append(c)
    for (d, slot), items in buckets.items():
        start = datetime.combine(d, datetime.min.time(), IST) + timedelta(minutes=SESSION_OPEN_MIN + slot * n)
        end_last_minute = start + timedelta(minutes=n - 1)
        is_closed = last_ts > end_last_minute or any(c.ts == end_last_minute for c in items)
        if not is_closed:
            continue
        items = sorted(items, key=lambda c: c.ts)
        out.append(
            Candle(
                instrument_id=items[0].instrument_id, timeframe=tf, ts=start,
                open=items[0].open, high=max(c.high for c in items), low=min(c.low for c in items),
                close=items[-1].close, volume=sum(c.volume for c in items), source=items[0].source,
                quality="ok" if len(items) == n else "gap",
            )
        )
    out.sort(key=lambda c: c.ts)
    return out


def forming_bar(closed_1m: list[Candle], current: Candle | None, tf: Timeframe) -> Candle | None:
    """The still-open `tf` bar: the live 1m candle plus the closed 1m candles of the same bucket and day.
    For display only: strategy and indicators never see it. Missing minutes stay missing (quality='gap')."""
    if current is None:
        return None
    n = TF_MINUTES[tf]
    key = (current.ts.date(), _slot(current.ts, n))
    items = [c for c in closed_1m if c.ts < current.ts and (c.ts.date(), _slot(c.ts, n)) == key] + [current]
    start = datetime.combine(key[0], datetime.min.time(), IST) + timedelta(minutes=SESSION_OPEN_MIN + key[1] * n)
    return Candle(
        instrument_id=items[0].instrument_id, timeframe=tf, ts=start, open=items[0].open,
        high=max(c.high for c in items), low=min(c.low for c in items), close=items[-1].close,
        volume=sum(c.volume for c in items), source=items[0].source, quality="ok" if len(items) == n else "gap",
    )
