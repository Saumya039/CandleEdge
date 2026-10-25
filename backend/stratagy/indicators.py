"""Pure indicator functions over numpy arrays. NaN marks 'not yet defined' (never back-filled).

Conventions (documented so tests can pin them):
* EMA: seeded with the SMA of the first `period` values; alpha = 2 / (period + 1).
* RSI / ATR / ADX: Wilder smoothing; ATR seeded with the mean of the first `period` true ranges
  (TR[0] = high - low).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np

from .models import Candle

NAN = float("nan")
Arr = Sequence[float] | np.ndarray


def ema(values: Arr, period: int) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    if period < 1 or len(v) < period:
        return out
    out[period - 1] = v[:period].mean()
    alpha = 2.0 / (period + 1)
    for i in range(period, len(v)):
        out[i] = alpha * v[i] + (1 - alpha) * out[i - 1]
    return out


def _wilder(values: np.ndarray, period: int, start: int) -> np.ndarray:
    """Wilder smoothing seeded with mean of values[start:start+period] placed at index start+period-1."""
    out = np.full(values.shape, np.nan)
    end = start + period
    if len(values) < end:
        return out
    out[end - 1] = values[start:end].mean()
    for i in range(end, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def rsi(closes: Arr, period: int = 14) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    out = np.full(c.shape, np.nan)
    if len(c) <= period:
        return out
    d = np.diff(c)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = gain[:period].mean()
    al = loss[:period].mean()

    def calc(g: float, l_: float) -> float:
        if l_ == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l_)

    out[period] = calc(ag, al)
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + gain[i]) / period
        al = (al * (period - 1) + loss[i]) / period
        out[i + 1] = calc(ag, al)
    return out


def true_range(high: Arr, low: Arr, close: Arr) -> np.ndarray:
    h, l_, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    tr = h - l_
    if len(c) > 1:
        tr[1:] = np.maximum.reduce([h[1:] - l_[1:], np.abs(h[1:] - c[:-1]), np.abs(l_[1:] - c[:-1])])
    return tr


def atr(high: Arr, low: Arr, close: Arr, period: int = 14) -> np.ndarray:
    return _wilder(true_range(high, low, close), period, 0)


def adx(high: Arr, low: Arr, close: Arr, period: int = 14) -> np.ndarray:
    h, l_, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    n = len(c)
    out = np.full(n, np.nan)
    if n < 2 * period + 1:
        return out
    up = h[1:] - h[:-1]
    dn = l_[:-1] - l_[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(h, l_, c)[1:]
    # Wilder sums (not means) so DI ratios are scale-free
    def smooth_sum(x: np.ndarray) -> np.ndarray:
        s = np.full(x.shape, np.nan)
        s[period - 1] = x[:period].sum()
        for i in range(period, len(x)):
            s[i] = s[i - 1] - s[i - 1] / period + x[i]
        return s

    str_, spdm, smdm = smooth_sum(tr), smooth_sum(plus_dm), smooth_sum(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * spdm / str_
        mdi = 100 * smdm / str_
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.where(np.isfinite(dx), dx, 0.0)
    dx = np.where(np.isnan(str_), np.nan, dx)
    first = period - 1
    adx_s = np.full(dx.shape, np.nan)
    seed_end = first + period
    if len(dx) < seed_end:
        return out
    adx_s[seed_end - 1] = dx[first:seed_end].mean()
    for i in range(seed_end, len(dx)):
        adx_s[i] = (adx_s[i - 1] * (period - 1) + dx[i]) / period
    out[1:] = adx_s
    return out


def session_vwap(candles: Sequence[Candle]) -> np.ndarray:
    """Cumulative VWAP using typical price (H+L+C)/3 weighted by volume, reset each IST calendar day.
    NaN where cumulative volume is zero (e.g. cash indices): VWAP is then 'Unavailable', never faked."""
    out = np.full(len(candles), np.nan)
    cum_pv = cum_v = 0.0
    day = None
    for i, c in enumerate(candles):
        d = c.ts.date()
        if d != day:
            day, cum_pv, cum_v = d, 0.0, 0.0
        tp = (c.high + c.low + c.close) / 3.0
        cum_pv += tp * c.volume
        cum_v += c.volume
        if cum_v > 0:
            out[i] = cum_pv / cum_v
    return out


def opening_range(
    candles_1m: Sequence[Candle], session_open: datetime, or_minutes: int
) -> tuple[float, float, bool]:
    """(high, low, complete). Complete only when every 1m bar of the window is present."""
    window = [c for c in candles_1m if session_open <= c.ts < session_open + timedelta(minutes=or_minutes)]
    if not window:
        return NAN, NAN, False
    complete = len(window) == or_minutes and len({c.ts for c in window}) == or_minutes
    return max(c.high for c in window), min(c.low for c in window), complete


def swing_points(
    high: Arr, low: Arr, left: int, right: int
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Confirmed pivot highs/lows. A pivot at i needs `right` later bars, so it is only reported once those
    bars exist (no look-ahead relative to the last index)."""
    h, l_ = np.asarray(high, dtype=float), np.asarray(low, dtype=float)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(left, len(h) - right):
        if h[i] > h[i - left : i].max() and h[i] >= h[i + 1 : i + 1 + right].max():
            highs.append((i, float(h[i])))
        if l_[i] < l_[i - left : i].min() and l_[i] <= l_[i + 1 : i + 1 + right].min():
            lows.append((i, float(l_[i])))
    return highs, lows


def slope_pct(series: np.ndarray, bars: int = 3) -> float:
    """Percent change of the series over the last `bars` steps; NaN if not defined."""
    if len(series) <= bars or np.isnan(series[-1]) or np.isnan(series[-1 - bars]) or series[-1 - bars] == 0:
        return NAN
    return 100.0 * (series[-1] - series[-1 - bars]) / series[-1 - bars]
