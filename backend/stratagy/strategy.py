"""Deterministic, explainable, versioned rule-based strategy (long CALL / long PUT only).

Nothing here uses randomness or any information after `snapshot.now`. Every number in a plan is derived from
candles/quotes in the snapshot plus parameters in config.StrategyParams."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
from pydantic import BaseModel, Field

from . import indicators as ind
from .candles import resample
from .config import ContractParams, CostModel, DataHealthParams, RiskSettings, StrategyParams
from .contracts import ContractChoice, choose_expiry, select_contract
from .models import (
    IST,
    TF_MINUTES,
    Candle,
    DataStatus,
    Direction,
    Instrument,
    OptionChainSnapshot,
    OptionQuote,
    ProviderHealth,
    Regime,
)
from .risk import Check, buy_fill, round_trip_costs, sell_fill, size_position
from .sessions import ExchangeCalendar, SessionPhase


class Snapshot(BaseModel):
    underlying: str
    now: datetime
    candles_1m: list[Candle]  # CLOSED 1m candles only, ascending, including prior-day history
    spot: float | None
    last_tick_ts: datetime | None
    health: ProviderHealth
    phase: SessionPhase
    chain: OptionChainSnapshot | None = None
    chain_error: str | None = None
    session_open: datetime | None = None


class RegimeResult(BaseModel):
    regime: Regime
    reasons: list[str] = Field(default_factory=list)
    close: float | None = None
    ema_fast: float | None = None
    ema_mid: float | None = None
    ema_slow: float | None = None
    vwap: float | None = None
    adx: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    rsi: float | None = None
    ema_mid_slope_pct: float | None = None
    bars: int = 0


def _f(x: float) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def _arrays(candles: list[Candle]):
    return (np.array([c.high for c in candles]), np.array([c.low for c in candles]),
            np.array([c.close for c in candles]), np.array([c.volume for c in candles]))


def classify_regime(bars: list[Candle], p: StrategyParams) -> RegimeResult:
    n = len(bars)
    if n < p.min_bars:
        return RegimeResult(regime=Regime.INSUFFICIENT_DATA, bars=n,
                            reasons=[f"Only {n} closed {p.trigger_tf} bars; need {p.min_bars}"])
    h, l_, c, _ = _arrays(bars)
    e_f, e_m, e_s = ind.ema(c, p.ema_fast), ind.ema(c, p.ema_mid), ind.ema(c, p.ema_slow)
    a = ind.atr(h, l_, c, p.atr_period)
    d = ind.adx(h, l_, c, p.adx_period)
    r = ind.rsi(c, p.rsi_period)
    v = ind.session_vwap(bars)
    res = RegimeResult(
        regime=Regime.INSUFFICIENT_DATA, bars=n, close=float(c[-1]), ema_fast=_f(e_f[-1]), ema_mid=_f(e_m[-1]),
        ema_slow=_f(e_s[-1]), vwap=_f(v[-1]), adx=_f(d[-1]), atr=_f(a[-1]), rsi=_f(r[-1]),
        ema_mid_slope_pct=_f(ind.slope_pct(e_m, 3)),
    )
    if res.atr:
        res.atr_pct = 100.0 * res.atr / float(c[-1])
    missing = [k for k in ("ema_fast", "ema_mid", "ema_slow", "adx", "atr", "rsi") if getattr(res, k) is None]
    if missing:
        res.reasons.append(f"Indicators not yet defined: {', '.join(missing)}")
        return res
    if res.vwap is None:
        res.reasons.append("VWAP unavailable (no volume in candles); regime cannot be classified")
        return res
    assert res.atr_pct is not None and res.adx is not None and res.ema_mid_slope_pct is not None
    assert res.close is not None and res.ema_fast is not None and res.ema_mid is not None and res.ema_slow is not None
    assert res.vwap is not None
    if res.atr_pct > p.high_vol_atr_pct:
        res.regime = Regime.HIGH_VOLATILITY
        res.reasons.append(f"ATR {res.atr_pct:.2f}% of price > {p.high_vol_atr_pct}% limit")
        return res
    up = res.ema_fast > res.ema_mid > res.ema_slow and res.close > res.vwap and res.ema_mid_slope_pct > 0
    dn = res.ema_fast < res.ema_mid < res.ema_slow and res.close < res.vwap and res.ema_mid_slope_pct < 0
    if up and res.adx >= p.adx_min_trend:
        res.regime = Regime.TRENDING_UP
        res.reasons.append(f"EMA{p.ema_fast}>EMA{p.ema_mid}>EMA{p.ema_slow}, close>VWAP, ADX {res.adx:.1f}>={p.adx_min_trend}")
    elif dn and res.adx >= p.adx_min_trend:
        res.regime = Regime.TRENDING_DOWN
        res.reasons.append(f"EMA{p.ema_fast}<EMA{p.ema_mid}<EMA{p.ema_slow}, close<VWAP, ADX {res.adx:.1f}>={p.adx_min_trend}")
    else:
        res.regime = Regime.RANGE_CHOP
        res.reasons.append("Trend conditions not all satisfied (EMA stack / VWAP / slope / ADX)")
    return res


class ScoreComponent(BaseModel):
    name: str
    weight: float
    fraction: float  # 0..1
    points: float
    detail: str


class TradePlan(BaseModel):
    direction: Direction
    underlying: str
    contract: Instrument
    quote: OptionQuote
    trigger_type: str
    trigger_level: float
    entry_zone_underlying: tuple[float, float]
    entry_ref_underlying: float
    invalidation_underlying: float
    target1_underlying: float
    target2_underlying: float
    stop_method: str
    target_method: str
    atr: float
    delta_used: float
    delta_source: str
    entry_premium_assumed: float  # conservative paper fill (ask + slippage)
    premium_stop: float  # premium risk-control level (estimate from delta; not guaranteed to fill)
    premium_target1: float
    premium_target2: float
    premium_entry_limit: float
    spread_pct: float
    lot_size: int
    lots: int
    per_lot_risk: float
    per_lot_reward_t1: float
    rr_t1: float
    rr_t2: float
    est_costs_round_trip_per_lot: float
    time_stop: datetime
    expiry_dt_note: str = ""
    warnings: list[str] = Field(default_factory=list)


class Evaluation(BaseModel):
    underlying: str
    ts: datetime
    strategy_version: str
    trigger_tf: str
    decision: str  # CANDIDATE | NO_TRADE
    direction: Direction | None = None
    regime: RegimeResult
    htf_regime: str | None = None
    reasons: list[str] = Field(default_factory=list)  # why NO_TRADE, or why CANDIDATE
    checks: list[Check] = Field(default_factory=list)
    plan: TradePlan | None = None
    score: float | None = None
    score_components: list[ScoreComponent] = Field(default_factory=list)
    trigger_bar_ts: datetime | None = None
    contract_choice: ContractChoice | None = None
    indicators: dict[str, float | None] = Field(default_factory=dict)
    levels: dict[str, float | None] = Field(default_factory=dict)
    data_sources: list[str] = Field(default_factory=list)
    needs_chain: bool = False  # all pre-chain conditions passed; engine should fetch the chain and re-evaluate

    @property
    def dedupe_key(self) -> str | None:
        if self.decision != "CANDIDATE" or not self.trigger_bar_ts or not self.direction:
            return None
        return f"{self.strategy_version}|{self.underlying}|{self.direction.value}|{self.trigger_tf}|{self.trigger_bar_ts.isoformat()}"


def data_quality_checks(s: Snapshot, p: StrategyParams, dh: DataHealthParams, bars: list[Candle],
                        cal: ExchangeCalendar) -> list[Check]:
    out: list[Check] = []
    ph = s.phase
    out.append(Check(name="session_phase", passed=ph == SessionPhase.TRADING, detail=f"Session phase {ph.value}"))
    hs = s.health
    status_ok = hs.status == DataStatus.LIVE or hs.status == DataStatus.SIMULATED or (
        hs.status == DataStatus.DELAYED and dh.accept_delayed)
    out.append(Check(name="feed_status", passed=status_ok and hs.connected,
                     detail=f"Provider {hs.name}: {hs.status.value}, {'connected' if hs.connected else 'DISCONNECTED'}"))
    age = None if s.last_tick_ts is None else (s.now - s.last_tick_ts).total_seconds()
    out.append(Check(name="tick_fresh", passed=age is not None and -dh.max_clock_skew_s <= age <= dh.stale_after_s,
                     detail="No tick received" if age is None else f"Last underlying tick {age:.1f}s ago (limit {dh.stale_after_s}s)"))
    if s.last_tick_ts is not None and hs.status == DataStatus.LIVE:
        skew = abs((s.now - s.last_tick_ts).total_seconds())
        out.append(Check(name="clock_skew", passed=skew <= dh.max_clock_skew_s, detail=f"Local vs exchange clock {skew:.1f}s"))
    tail = bars[-dh.gap_check_bars:]
    step = timedelta(minutes=TF_MINUTES[p.trigger_tf])
    contiguous = True
    for a, b in zip(tail, tail[1:], strict=False):
        if b.ts.date() == a.ts.date() and b.ts - a.ts != step:
            contiguous = False
    ok_q = all(c.quality == "ok" for c in tail)
    out.append(Check(name="candle_integrity", passed=contiguous and ok_q and len(tail) > 0,
                     detail="No gaps/duplicates in recent bars" if contiguous and ok_q else "Gap or duplicate in recent candles"))
    if s.session_open is not None:
        o1 = [c for c in s.candles_1m if c.ts.date() == s.session_open.date()]
        hi, lo, complete = ind.opening_range(o1, s.session_open, p.or_minutes)
        out.append(Check(name="opening_range_formed", passed=complete,
                         detail=f"Opening range {p.or_minutes}m " + (f"{lo:.2f}-{hi:.2f}" if complete else "not complete")))
    out.append(Check(name="calendar", passed=True,
                     detail="Exchange calendar configured" if cal.verified else "Calendar file not configured: holidays unverified"))
    return out


def _recent_swing_levels(bars: list[Candle], p: StrategyParams):
    seg = bars[-p.swing_lookback:]
    h, l_ = [c.high for c in seg], [c.low for c in seg]
    highs, lows = ind.swing_points(h, l_, p.swing_left, p.swing_right)
    return [x[1] for x in highs], [x[1] for x in lows]


def evaluate(s: Snapshot, p: StrategyParams, cp: ContractParams, cost: CostModel, risk: RiskSettings,
             dh: DataHealthParams, gates: list[Check], cal: ExchangeCalendar) -> Evaluation:
    bars = resample(s.candles_1m, p.trigger_tf)
    regime = classify_regime(bars, p)
    ev = Evaluation(underlying=s.underlying, ts=s.now, strategy_version=p.version, trigger_tf=p.trigger_tf,
                    decision="NO_TRADE", regime=regime,
                    trigger_bar_ts=bars[-1].ts if bars else None,
                    data_sources=[f"{s.health.name}:{s.health.status.value}"])
    ev.indicators = {k: getattr(regime, k) for k in ("close", "ema_fast", "ema_mid", "ema_slow", "vwap", "adx", "atr",
                                                       "atr_pct", "rsi", "ema_mid_slope_pct")}
    checks = data_quality_checks(s, p, dh, bars, cal) + gates
    ev.checks = checks
    failed = [c for c in checks if not c.passed]
    if failed:
        ev.reasons = [f"{c.name}: {c.detail}" for c in failed]
        return ev  # fail closed
    if regime.regime in (Regime.INSUFFICIENT_DATA, Regime.RANGE_CHOP, Regime.HIGH_VOLATILITY):
        ev.reasons = [f"Regime {regime.regime.value}: " + "; ".join(regime.reasons)]
        return ev
    direction = Direction.CALL if regime.regime == Regime.TRENDING_UP else Direction.PUT
    ev.direction = direction
    sign = 1 if direction == Direction.CALL else -1
    h, l_, c, vol = _arrays(bars)
    atr_v = regime.atr
    assert atr_v is not None and regime.close is not None and regime.ema_fast is not None

    # ---- higher-timeframe confirmation (must exist) ----
    htf_bars = resample(s.candles_1m, p.htf)
    htf = classify_regime(htf_bars, p.model_copy(update={"min_bars": p.ema_slow + 10}))
    ev.htf_regime = htf.regime.value
    htf_ok = htf.ema_fast is not None and htf.ema_mid is not None and sign * (htf.ema_fast - htf.ema_mid) > 0
    if not htf_ok:
        ev.reasons = [f"Higher timeframe {p.htf} does not confirm (EMA{p.ema_fast} vs EMA{p.ema_mid}; regime {htf.regime.value})"]
        return ev

    # ---- momentum / volume ----
    rsi_v = regime.rsi or 0.0
    rsi_ok = (p.rsi_long_min <= rsi_v <= p.rsi_long_max) if sign > 0 else (p.rsi_short_min <= rsi_v <= p.rsi_short_max)
    if not rsi_ok:
        ev.reasons = [f"Momentum does not confirm: RSI {rsi_v:.1f}"]
        return ev
    vavg = float(vol[-1 - p.volume_lookback:-1].mean()) if len(vol) > p.volume_lookback else 0.0
    vol_ratio = float(vol[-1] / vavg) if vavg > 0 else None
    if p.require_volume and (vol_ratio is None or vol_ratio < p.volume_mult_min):
        ev.reasons = ["Volume unavailable: cannot confirm" if vol_ratio is None
                      else f"Volume does not confirm: last bar {vol_ratio:.2f}x average (< {p.volume_mult_min}x)"]
        return ev

    # ---- trigger: breakout or pullback retest ----
    lb = p.breakout_lookback
    prior_hi, prior_lo = float(h[-1 - lb:-1].max()), float(l_[-1 - lb:-1].min())
    trigger_type, trigger_level = "", 0.0
    if sign > 0:
        if c[-1] > prior_hi:
            trigger_type, trigger_level = "BREAKOUT", prior_hi
        elif l_[-1] <= (regime.ema_mid or 0) * 1.0005 and c[-1] > regime.ema_fast and c[-1] > h[-2]:
            trigger_type, trigger_level = "PULLBACK_RETEST", float(h[-2])
    else:
        if c[-1] < prior_lo:
            trigger_type, trigger_level = "BREAKDOWN", prior_lo
        elif h[-1] >= (regime.ema_mid or 0) * 0.9995 and c[-1] < regime.ema_fast and c[-1] < l_[-2]:
            trigger_type, trigger_level = "PULLBACK_RETEST", float(l_[-2])
    if not trigger_type:
        ev.reasons = [f"Trend present but no trigger: no {lb}-bar {'high' if sign > 0 else 'low'} break and no EMA{p.ema_mid} retest"]
        return ev
    extension = sign * (c[-1] - regime.ema_fast) / atr_v
    if extension > p.max_extension_atr:
        ev.reasons = [f"Too extended: close is {extension:.2f} ATR from EMA{p.ema_fast} (> {p.max_extension_atr})"]
        return ev

    # ---- levels (underlying) ----
    sw_highs, sw_lows = _recent_swing_levels(bars, p)
    zone_hi_ext = p.entry_zone_atr * atr_v
    lo_z, hi_z = (trigger_level, trigger_level + zone_hi_ext) if sign > 0 else (trigger_level - zone_hi_ext, trigger_level)
    entry_ref = hi_z if sign > 0 else lo_z  # conservative: worst price of the zone
    if sign > 0:
        stops = [x for x in sw_lows if x < lo_z]
        raw_stop = max(stops) if stops else None
        stop_u = None if raw_stop is None else raw_stop - p.stop_atr_buffer * atr_v
    else:
        stops = [x for x in sw_highs if x > hi_z]
        raw_stop = min(stops) if stops else None
        stop_u = None if raw_stop is None else raw_stop + p.stop_atr_buffer * atr_v
    if stop_u is None:
        ev.reasons = ["NO TRADE: risk levels unavailable (no confirmed swing structure for invalidation)"]
        return ev
    risk_u = sign * (entry_ref - stop_u)
    if not (p.min_stop_atr * atr_v <= risk_u <= p.max_stop_atr * atr_v):
        ev.reasons = [f"NO TRADE: risk levels unavailable (stop distance {risk_u / atr_v:.2f} ATR outside "
                      f"{p.min_stop_atr}-{p.max_stop_atr} ATR)"]
        return ev
    t1 = entry_ref + sign * p.t1_r * risk_u
    t2 = entry_ref + sign * p.t2_r * risk_u
    day = [x for x in s.candles_1m if s.session_open and x.ts.date() == s.session_open.date()]
    day_hi = max((x.high for x in day), default=None)
    day_lo = min((x.low for x in day), default=None)
    res_cands = [x for x in sw_highs if x > entry_ref] if sign > 0 else [x for x in sw_lows if x < entry_ref]
    if sign > 0 and day_hi and day_hi > entry_ref:
        res_cands.append(day_hi)
    if sign < 0 and day_lo and day_lo < entry_ref:
        res_cands.append(day_lo)
    resistance = (min(res_cands) if sign > 0 else max(res_cands)) if res_cands else None
    target_method = f"{p.t1_r}R / {p.t2_r}R of underlying risk"
    if resistance is not None and sign * (t1 - resistance) > 0:
        t1 = resistance - sign * 0.1 * atr_v
        target_method = f"T1 capped at next {'resistance' if sign > 0 else 'support'} {resistance:.2f}"
        if sign * (t2 - resistance) > 0:
            t2 = max(t2, t1) if sign > 0 else min(t2, t1)  # T2 stays beyond T1 (shown with warning)
    room_r = sign * (t1 - entry_ref) / risk_u
    ev.levels = {"trigger_level": trigger_level, "entry_lo": lo_z, "entry_hi": hi_z, "invalidation": stop_u,
                 "target1": t1, "target2": t2, "resistance_or_support": resistance, "day_high": day_hi, "day_low": day_lo,
                 "room_to_t1_r": room_r}

    # ---- contract ----
    if s.chain is None:
        ev.needs_chain = s.chain_error is None
        ev.reasons = [f"Option chain unavailable{': ' + s.chain_error if s.chain_error else ''}"]
        return ev
    chain_ok = s.chain.status in (DataStatus.LIVE, DataStatus.SIMULATED) or (
        s.chain.status == DataStatus.DELAYED and dh.accept_delayed)
    if not chain_ok:
        ev.reasons = [f"Option chain status {s.chain.status.value}"]
        return ev
    choice = select_contract(s.chain, direction, s.now, cp)
    ev.contract_choice = choice
    q = choice.quote
    if q is None:
        ev.reasons = ["No liquid, fresh contract: " + ", ".join(f"{k} x{v}" for k, v in sorted(choice.rejected.items()))]
        return ev
    assert q.greeks and q.greeks.delta is not None and q.ask and q.bid
    delta = abs(q.greeks.delta)
    tick = q.instrument.tick_size
    entry_fill = buy_fill(q.ask, tick, cost)
    prem_stop = entry_fill - delta * risk_u
    prem_stop = max(prem_stop, entry_fill * 0.5)  # premium risk-control floor: never model a >50% stop distance
    t1_prem = entry_fill + delta * abs(t1 - entry_ref)
    t2_prem = entry_fill + delta * abs(t2 - entry_ref)
    lot = q.instrument.lot_size
    exit_fill_stop = sell_fill(prem_stop, tick, cost)
    exit_fill_t1 = sell_fill(t1_prem, tick, cost)
    costs_stop = round_trip_costs(entry_fill, exit_fill_stop, lot, cost)
    costs_t1 = round_trip_costs(entry_fill, exit_fill_t1, lot, cost)
    per_lot_risk = max(entry_fill - exit_fill_stop, 0) * lot + costs_stop
    per_lot_reward = (exit_fill_t1 - entry_fill) * lot - costs_t1
    rr1 = per_lot_reward / per_lot_risk if per_lot_risk > 0 else 0.0
    exit_fill_t2 = sell_fill(t2_prem, tick, cost)
    rr2 = ((exit_fill_t2 - entry_fill) * lot - round_trip_costs(entry_fill, exit_fill_t2, lot, cost)) / per_lot_risk if per_lot_risk > 0 else 0.0
    min_rr = max(p.min_rr, risk.min_reward_risk)
    if rr1 < min_rr:
        ev.reasons = [f"Reward/risk {rr1:.2f} (net of spread, slippage, costs) < minimum {min_rr:.2f}"
                      + (f"; limited room to {resistance:.2f}" if resistance is not None and room_r < p.t1_r else "")]
        return ev
    sizing = size_position(entry_fill, prem_stop, lot, tick, cost, risk)
    if sizing.lots < 1:
        ev.reasons = [f"NO TRADE: {sizing.reason}"]
        return ev

    # ---- score (transparent, NOT a probability) ----
    w = p.score_weights
    comps = [
        ("trend_strength", min(max(((regime.adx or 0) - p.adx_min_trend) / 20.0, 0.0), 1.0) * 0.6 + 0.4, f"ADX {regime.adx:.1f}"),
        ("htf_alignment", 1.0, f"{p.htf} EMA{p.ema_fast}/{p.ema_mid} aligned ({htf.regime.value})"),
        ("vwap_ema_structure", min(abs(regime.close - regime.vwap) / atr_v, 2.0) / 2.0 * 0.5 + 0.5 if regime.vwap else 0.5,
         f"close {'above' if sign > 0 else 'below'} VWAP, EMAs stacked"),
        ("momentum", 1.0 - min(abs(rsi_v - 65 if sign > 0 else rsi_v - 35) / 20.0, 1.0), f"RSI {rsi_v:.1f}"),
        ("volume", min((vol_ratio or 0.0) / 2.0, 1.0), f"last bar {vol_ratio:.2f}x avg" if vol_ratio else "n/a"),
        ("room_and_rr", min(rr1 / (2 * min_rr), 1.0), f"net R:R {rr1:.2f} to T1; room {room_r:.2f}R"),
        ("liquidity", max(1.0 - (q.spread_pct or 0) / cp.max_spread_pct, 0.0), f"spread {q.spread_pct:.2f}% / limit {cp.max_spread_pct}%"),
    ]
    ev.score_components = [ScoreComponent(name=n, weight=w[n], fraction=round(fr, 3), points=round(w[n] * fr, 2), detail=d)
                           for n, fr, d in comps]
    ev.score = round(sum(sc.points for sc in ev.score_components), 1)

    warnings = ["Estimated premium levels use delta (linear); actual option prices can gap, decay and move nonlinearly"]
    if q.greeks.source == "estimated":
        warnings.append("Greeks/IV are ESTIMATES (Black-76), not provider values")
    if q.status == DataStatus.SIMULATED:
        warnings.append("SIMULATED data: no real market, no real fills")
    if resistance is not None and sign * (t2 - resistance) > 0:
        warnings.append(f"Target 2 lies beyond the next {'resistance' if sign > 0 else 'support'} ({resistance:.2f})")
    plan = TradePlan(
        direction=direction, underlying=s.underlying, contract=q.instrument, quote=q, trigger_type=trigger_type,
        trigger_level=trigger_level, entry_zone_underlying=(lo_z, hi_z), entry_ref_underlying=entry_ref,
        invalidation_underlying=stop_u, target1_underlying=t1, target2_underlying=t2,
        stop_method=f"Confirmed {p.swing_left}/{p.swing_right} pivot {raw_stop:.2f} {'-' if sign > 0 else '+'} {p.stop_atr_buffer} ATR ({p.trigger_tf})",
        target_method=target_method, atr=atr_v, delta_used=delta, delta_source=q.greeks.source,
        entry_premium_assumed=entry_fill, premium_stop=round(prem_stop, 2), premium_target1=round(t1_prem, 2),
        premium_target2=round(t2_prem, 2), premium_entry_limit=round(entry_fill + delta * zone_hi_ext, 2),
        spread_pct=q.spread_pct or 0.0, lot_size=lot, lots=sizing.lots, per_lot_risk=round(per_lot_risk, 2),
        per_lot_reward_t1=round(per_lot_reward, 2), rr_t1=round(rr1, 2), rr_t2=round(rr2, 2),
        est_costs_round_trip_per_lot=round(costs_stop, 2),
        time_stop=s.now + timedelta(minutes=TF_MINUTES[p.trigger_tf] * p.time_stop_bars), warnings=warnings,
    )
    ev.plan = plan
    ev.decision = "CANDIDATE"
    why = [
        f"Regime {regime.regime.value} on {p.trigger_tf}: {regime.reasons[0]}",
        f"{p.htf} confirms (EMA{p.ema_fast} {'>' if sign > 0 else '<'} EMA{p.ema_mid})",
        f"{trigger_type} of {trigger_level:.2f}; RSI {rsi_v:.1f}; volume {vol_ratio:.2f}x avg" if vol_ratio else f"{trigger_type} of {trigger_level:.2f}; RSI {rsi_v:.1f}",
        f"Invalidation {stop_u:.2f} ({plan.stop_method}); T1 {t1:.2f}; T2 {t2:.2f}",
        f"Net R:R to T1 {rr1:.2f} (min {min_rr:.2f}) after spread {q.spread_pct:.2f}%, slippage and estimated costs",
    ]
    ev.reasons = why
    return ev


def pick_chain_expiry(chain_expiries, today, cp: ContractParams):
    return choose_expiry(list(chain_expiries), today, cp)


__all__ = ["Evaluation", "Snapshot", "TradePlan", "evaluate", "classify_regime", "RegimeResult", "pick_chain_expiry", "IST"]
