import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from stratagy import indicators as ind
from stratagy import pricing
from stratagy.models import IST, Candle, OptionType


def candle(ts, o, h, lo, c, v=100.0):
    return Candle(instrument_id="X", timeframe="1m", ts=ts, open=o, high=h, low=lo, close=c, volume=v)


def test_ema_hand_computed_fixture():
    out = ind.ema([1, 2, 3, 4, 5], 3)
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert out[2] == pytest.approx(2.0)  # SMA seed
    assert out[3] == pytest.approx(3.0)  # 0.5*4 + 0.5*2
    assert out[4] == pytest.approx(4.0)


def test_ema_constant_series_and_short_input():
    assert ind.ema([5.0] * 20, 9)[-1] == pytest.approx(5.0)
    assert np.isnan(ind.ema([1, 2], 5)).all()


def test_rsi_extremes_and_hand_example():
    up = ind.rsi(list(range(1, 30)), 14)
    assert up[-1] == pytest.approx(100.0)
    dn = ind.rsi(list(range(30, 1, -1)), 14)
    assert dn[-1] == pytest.approx(0.0)
    # period 2, closes 1,2,1: avg gain 0.5, avg loss 0.5 -> RSI 50
    assert ind.rsi([1, 2, 1], 2)[2] == pytest.approx(50.0)
    assert np.isnan(ind.rsi([1, 2], 2)).all()


def test_atr_constant_range():
    h = [11.0] * 30
    lo = [9.0] * 30
    c = [10.0] * 30
    assert ind.atr(h, lo, c, 14)[-1] == pytest.approx(2.0)
    assert np.isnan(ind.atr(h, lo, c, 14)[12])


def test_true_range_uses_gap_from_previous_close():
    tr = ind.true_range([10, 15], [9, 14], [9.5, 14.5])
    assert tr[1] == pytest.approx(5.5)  # |high - prev close|


def test_adx_trend_vs_chop():
    n = 120
    t = np.arange(n, dtype=float)
    h, lo, c = t + 1.0, t - 1.0, t
    assert ind.adx(h, lo, c, 14)[-1] > 40  # relentless trend
    chop = 100 + np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    assert ind.adx(chop + 0.5, chop - 0.5, chop, 14)[-1] < 15
    assert np.isnan(ind.adx(h[:20], lo[:20], c[:20], 14)).all()


def test_vwap_hand_example_and_daily_reset_and_no_volume():
    d1 = datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    d2 = datetime(2026, 1, 6, 9, 15, tzinfo=IST)
    cs = [
        candle(d1, 10, 12, 8, 10, 100),  # tp 10
        candle(d1 + timedelta(minutes=1), 10, 16, 10, 13, 300),  # tp 13
        candle(d2, 50, 50, 50, 50, 10),
    ]
    v = ind.session_vwap(cs)
    assert v[0] == pytest.approx(10.0)
    assert v[1] == pytest.approx((10 * 100 + 13 * 300) / 400)
    assert v[2] == pytest.approx(50.0)  # reset on new day
    nov = ind.session_vwap([candle(d1, 1, 1, 1, 1, 0)])
    assert np.isnan(nov[0])  # unavailable, never faked


def test_opening_range_complete_and_incomplete():
    o = datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    cs = [candle(o + timedelta(minutes=i), 100, 100 + i, 100 - i, 100) for i in range(15)]
    hi, lo, ok = ind.opening_range(cs, o, 15)
    assert (hi, lo, ok) == (114.0, 86.0, True)
    hi, lo, ok = ind.opening_range(cs[:10], o, 15)
    assert ok is False
    gap = cs[:5] + cs[6:]
    assert ind.opening_range(gap, o, 15)[2] is False  # missing minute -> not complete
    assert math.isnan(ind.opening_range([], o, 15)[0])


def test_swing_points_have_no_lookahead():
    h = [1, 2, 3, 2, 1, 2, 5, 4]
    lo = [x - 0.5 for x in h]
    highs, _ = ind.swing_points(h, lo, 2, 2)
    assert (2, 3) in highs
    assert all(i <= len(h) - 1 - 2 for i, _ in highs)  # pivot at index 6 (5) needs 2 later bars: not reported
    assert (6, 5) not in highs


def test_slope_pct():
    assert ind.slope_pct(np.array([100.0, 100, 100, 103]), 3) == pytest.approx(3.0)
    assert math.isnan(ind.slope_pct(np.array([1.0, 2.0]), 3))


def test_black76_parity_and_iv_roundtrip():
    f, k, t, s, r = 24500.0, 24500.0, 7 / 365, 0.15, pricing.DEFAULT_RATE
    c = pricing.price(f, k, t, s, OptionType.CE, r)
    p = pricing.price(f, k, t, s, OptionType.PE, r)
    assert c - p == pytest.approx(math.exp(-r * t) * (f - k), abs=1e-6)
    iv = pricing.implied_vol(c, f, k, t, OptionType.CE, r)
    assert iv == pytest.approx(s, abs=1e-6)
    assert pricing.implied_vol(0.0, f, k, t, OptionType.CE) is None
    assert pricing.implied_vol(1e9, f, k, t, OptionType.CE) is None  # outside bounds: None, not a guess
    g = pricing.greeks(f, k, t, s, OptionType.CE)
    assert 0.4 < g.delta < 0.6 and g.source == "estimated"
