"""Black-76 option maths used ONLY for estimates (simulator quotes and estimated Greeks/IV).

Assumptions (documented, not hidden): European exercise, forward price F supplied by the caller, constant
volatility per option, flat continuously-compounded rate `r`, calendar-time year fraction (365 days),
no dividend/borrow adjustments. Values derived here are always labelled `source="estimated"`.
"""

from __future__ import annotations

import math
from datetime import datetime

from .models import IST, Greeks, OptionType

DEFAULT_RATE = 0.065


def _n_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _n_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def year_fraction(now: datetime, expiry_dt: datetime) -> float:
    return max((expiry_dt.astimezone(IST) - now.astimezone(IST)).total_seconds(), 0.0) / (365.0 * 86400.0)


def price(f: float, k: float, t: float, sigma: float, kind: OptionType, r: float = DEFAULT_RATE) -> float:
    df = math.exp(-r * t)
    if t <= 0 or sigma <= 0:
        intrinsic = max(f - k, 0.0) if kind == OptionType.CE else max(k - f, 0.0)
        return df * intrinsic
    sd = sigma * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if kind == OptionType.CE:
        return df * (f * _n_cdf(d1) - k * _n_cdf(d2))
    return df * (k * _n_cdf(-d2) - f * _n_cdf(-d1))


def greeks(f: float, k: float, t: float, sigma: float, kind: OptionType, r: float = DEFAULT_RATE) -> Greeks:
    if t <= 0 or sigma <= 0:
        return Greeks(source="estimated")
    df = math.exp(-r * t)
    sd = sigma * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * sd * sd) / sd
    delta = df * (_n_cdf(d1) if kind == OptionType.CE else _n_cdf(d1) - 1.0)
    gamma = df * _n_pdf(d1) / (f * sd)
    vega = df * f * _n_pdf(d1) * math.sqrt(t) / 100.0
    dt = 1.0 / 365.0
    theta = price(f, k, max(t - dt, 0.0), sigma, kind, r) - price(f, k, t, sigma, kind, r)
    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, iv=sigma, source="estimated")


def implied_vol(
    target: float, f: float, k: float, t: float, kind: OptionType, r: float = DEFAULT_RATE
) -> float | None:
    """Bisection IV. Returns None (never a guess) when the price is outside no-arbitrage bounds."""
    if t <= 0 or target <= 0 or f <= 0 or k <= 0:
        return None
    lo, hi = 1e-4, 5.0
    if target < price(f, k, t, lo, kind, r) - 1e-9 or target > price(f, k, t, hi, kind, r) + 1e-9:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if price(f, k, t, mid, kind, r) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
