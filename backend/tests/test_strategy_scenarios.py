"""Strategy behaviour on bullish / bearish / no-trade conditions. Candidate scenarios come from the real engine on the
seeded SIMULATOR (see conftest); NO-TRADE cases mutate that snapshot one condition at a time."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from stratagy.config import DataHealthParams, RiskSettings, StrategyParams
from stratagy.models import IST, Candle, DataStatus, Direction, ProviderHealth, Regime
from stratagy.risk import RiskState, risk_gate
from stratagy.sessions import SessionPhase
from stratagy.strategy import classify_regime
from tests.conftest import (
    clean_gates,
    evaluate_with,
    first_signal_engine,
    snapshot_for,
)

CALL_SEED = 7  # NIFTY BUY_CALL candidate at 12:00:10


@pytest.fixture(scope="module")
def call_scenario():
    eng, prov = first_signal_engine(CALL_SEED)
    return eng, prov, next(iter(eng.signals.values()))


# ------------------------------------------------------------------ bullish / bearish candidates
def check_plan(sig, eng):
    p = sig.plan
    sign = 1 if sig.direction == Direction.CALL else -1
    lo, hi = p.entry_zone_underlying
    assert lo < hi
    assert sign * (p.entry_ref_underlying - p.invalidation_underlying) > 0  # stop is on the losing side
    assert sign * (p.target1_underlying - p.entry_ref_underlying) > 0
    assert sign * (p.target2_underlying - p.target1_underlying) >= 0
    assert p.premium_stop < p.entry_premium_assumed < p.premium_target1 <= p.premium_target2
    assert p.rr_t1 >= max(eng.p.min_rr, eng.risk.min_reward_risk)
    assert p.lots >= 1 and p.lots * p.per_lot_risk <= eng.risk.max_risk_per_trade
    assert p.lot_size == p.contract.lot_size > 0  # from instrument metadata, not hard-coded
    assert p.time_stop > sig.created_ts
    assert p.delta_source in ("estimated", "provider")
    assert p.quote.status == DataStatus.SIMULATED and any("SIMULATED" in w for w in p.warnings)
    assert sig.rationale and sig.strategy_version == eng.p.version and sig.trigger_tf == eng.p.trigger_tf
    assert sig.indicators["atr"] and sig.data_sources == ["simulator:SIMULATED"]
    assert sig.score == pytest.approx(sum(c.points for c in sig.score_components), abs=0.2)
    assert sum(c.weight for c in sig.score_components) == pytest.approx(100.0)
    assert all(0.0 <= c.fraction <= 1.0 for c in sig.score_components)


def test_bearish_candidate_is_buy_put_with_complete_plan(put_scenario):
    eng, _, sig = put_scenario
    assert sig.direction == Direction.PUT and sig.plan.contract.option_type.value == "PE"
    check_plan(sig, eng)


def test_bullish_candidate_is_buy_call_with_complete_plan(call_scenario):
    eng, _, sig = call_scenario
    assert sig.direction == Direction.CALL and sig.plan.contract.option_type.value == "CE"
    check_plan(sig, eng)


def test_evaluation_is_deterministic(put_scenario):
    eng, _, sig = put_scenario
    a = evaluate_with(eng, sig.underlying, gates=clean_gates(eng, sig.underlying))
    b = evaluate_with(eng, sig.underlying, gates=clean_gates(eng, sig.underlying))
    assert a.decision == "CANDIDATE"
    assert a.model_dump() == b.model_dump()


def test_no_hindsight_first_signal_identical_when_run_continues():
    """Run A stops at the first signal; run B continues to the close. The first signal must be identical."""
    import asyncio

    from tests.conftest import new_engine, run_until

    eng_a, _ = first_signal_engine(1)
    eng_b, prov_b = new_engine(1)
    asyncio.run(run_until(eng_b, prov_b, lambda e: False))
    a = next(iter(eng_a.signals.values()))
    b = eng_b.signals[a.id]
    assert a.plan.model_dump() == b.plan.model_dump()
    assert a.created_ts == b.created_ts and a.score == b.score


def test_engine_only_uses_closed_candles_up_to_now(put_scenario):
    eng, prov, sig = put_scenario
    now = prov.now()
    for st in eng.u.values():
        assert all(c.ts + timedelta(minutes=1) <= now + timedelta(seconds=1) for c in st.builder.closed_list())


def test_provider_history_never_returns_the_future(put_scenario):
    import asyncio

    _, prov, _ = put_scenario
    cs = asyncio.run(prov.get_historical_candles("SIM:NIFTY", "1m", prov.now() - timedelta(days=9), prov.now() + timedelta(days=2)))
    assert cs and all(c.ts + timedelta(minutes=1) <= prov.now() for c in cs)


# ------------------------------------------------------------------ NO TRADE: one cause at a time
def reasons(ev):
    return " | ".join(ev.reasons)


@pytest.fixture
def base(put_scenario):
    eng, prov, sig = put_scenario
    return eng, sig.underlying, snapshot_for(eng, sig.underlying)


def test_baseline_is_candidate(base):
    eng, und, snap = base
    assert evaluate_with(eng, und, snap).decision == "CANDIDATE"


def test_stale_ticks_fail_closed(base):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap.model_copy(update={"last_tick_ts": snap.now - timedelta(seconds=60)}))
    assert ev.decision == "NO_TRADE" and "tick_fresh" in reasons(ev) and ev.plan is None


def test_no_tick_at_all_fails_closed(base):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap.model_copy(update={"last_tick_ts": None}))
    assert ev.decision == "NO_TRADE" and "No tick received" in reasons(ev)


def test_disconnected_feed_fails_closed(base):
    eng, und, snap = base
    h = snap.health.model_copy(update={"connected": False})
    ev = evaluate_with(eng, und, snap.model_copy(update={"health": h}))
    assert ev.decision == "NO_TRADE" and "feed_status" in reasons(ev)


def test_delayed_data_needs_explicit_acceptance(base):
    eng, und, snap = base
    h = snap.health.model_copy(update={"status": DataStatus.DELAYED})
    s = snap.model_copy(update={"health": h})
    assert "feed_status" in reasons(evaluate_with(eng, und, s))
    ok = evaluate_with(eng, und, s, dh=DataHealthParams(accept_delayed=True))
    assert "feed_status" not in reasons(ok)


def test_stale_provider_status_blocks(base):
    eng, und, snap = base
    h = snap.health.model_copy(update={"status": DataStatus.STALE})
    assert "feed_status" in reasons(evaluate_with(eng, und, snap.model_copy(update={"health": h})))


@pytest.mark.parametrize("phase", [SessionPhase.OPENING_RANGE, SessionPhase.NO_NEW_ENTRIES, SessionPhase.POST_CLOSE,
                                   SessionPhase.PRE_MARKET, SessionPhase.CLOSED])
def test_only_trading_phase_allows_entries(base, phase):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap.model_copy(update={"phase": phase}))
    assert ev.decision == "NO_TRADE" and "session_phase" in reasons(ev)


def test_candle_gap_blocks(base):
    eng, und, snap = base
    cs = list(snap.candles_1m)
    del cs[-3]  # a missing minute inside the latest bars
    ev = evaluate_with(eng, und, snap.model_copy(update={"candles_1m": cs}))
    assert ev.decision == "NO_TRADE" and "candle_integrity" in reasons(ev)


def test_insufficient_history_is_insufficient_data(base):
    eng, und, snap = base
    today = [c for c in snap.candles_1m if c.ts.date() == snap.now.date()]
    ev = evaluate_with(eng, und, snap.model_copy(update={"candles_1m": today}))
    assert ev.decision == "NO_TRADE" and ev.regime.regime == Regime.INSUFFICIENT_DATA


def test_unresolved_chain_blocks(base):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap.model_copy(update={"chain": None, "chain_error": "boom"}))
    assert ev.decision == "NO_TRADE" and "Option chain unavailable" in reasons(ev)


def test_wide_spreads_block_contract_selection(base):
    eng, und, snap = base
    chain = snap.chain.model_copy(deep=True)
    for r in chain.rows:
        for q in (r.ce, r.pe):
            if q and q.bid:
                q.bid = round(q.ask * 0.5, 2)
    ev = evaluate_with(eng, und, snap.model_copy(update={"chain": chain}))
    assert ev.decision == "NO_TRADE" and "spread too wide" in reasons(ev)


def test_stale_option_quotes_block(base):
    eng, und, snap = base
    chain = snap.chain.model_copy(deep=True)
    for r in chain.rows:
        for q in (r.ce, r.pe):
            if q:
                q.received_ts = snap.now - timedelta(minutes=5)
    ev = evaluate_with(eng, und, snap.model_copy(update={"chain": chain}))
    assert ev.decision == "NO_TRADE" and "stale quote" in reasons(ev)


def test_missing_greeks_means_risk_levels_unavailable_not_invented(base):
    eng, und, snap = base
    chain = snap.chain.model_copy(deep=True)
    for r in chain.rows:
        for q in (r.ce, r.pe):
            if q:
                q.greeks = None
    ev = evaluate_with(eng, und, snap.model_copy(update={"chain": chain}))
    assert ev.decision == "NO_TRADE" and "delta unavailable" in reasons(ev)


def test_min_lot_exceeding_risk_budget(base):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap, risk=RiskSettings(confirmed=True, max_risk_per_trade=50))
    assert ev.decision == "NO_TRADE" and "Minimum lot exceeds risk budget" in reasons(ev)


def test_reward_risk_threshold_blocks(base):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap, risk=RiskSettings(confirmed=True, min_reward_risk=9.0))
    assert ev.decision == "NO_TRADE" and "Reward/risk" in reasons(ev)


@pytest.mark.parametrize("state,name", [
    (RiskState(realized_net=-1e9), "daily_loss_limit"),
    (RiskState(trades_today=99), "max_trades"),
    (RiskState(open_positions=5), "max_open_positions"),
    (RiskState(paused=True, pause_reason="manual"), "not_paused"),
])
def test_risk_limits_block_new_signals(base, state, name):
    eng, und, snap = base
    gates = risk_gate(snap.now, state, eng.risk, eng._cutoff_dt(snap.now))
    ev = evaluate_with(eng, und, snap, gates=gates)
    assert ev.decision == "NO_TRADE" and name in reasons(ev)


def test_unconfirmed_risk_settings_block(base):
    eng, und, snap = base
    gates = risk_gate(snap.now, eng.risk_state, RiskSettings(confirmed=False), eng._cutoff_dt(snap.now))
    ev = evaluate_with(eng, und, snap, gates=gates)
    assert "risk_settings_confirmed" in reasons(ev)


def test_late_entry_after_cutoff_blocked(base):
    eng, und, snap = base
    late = snap.now.replace(hour=15, minute=20)
    gates = risk_gate(late, eng.risk_state, eng.risk, eng._cutoff_dt(late))
    ev = evaluate_with(eng, und, snap.model_copy(update={"phase": SessionPhase.NO_NEW_ENTRIES}), gates=gates)
    assert ev.decision == "NO_TRADE" and "before_cutoff" in reasons(ev)


# ------------------------------------------------------------------ regime classification on crafted data
def mk_bars(closes, vols=None, spread=20.0, start=datetime(2026, 10, 23, 9, 15, tzinfo=IST), tf="5m"):
    out = []
    step = timedelta(minutes=5)
    for i, c in enumerate(closes):
        out.append(Candle(instrument_id="X", timeframe=tf, ts=start + step * i, open=c, high=c + spread, low=c - spread,
                          close=c, volume=float(vols[i] if vols is not None else 1000)))
    return out


P = StrategyParams()


def test_regime_trending_up_and_down():
    t = np.arange(70, dtype=float)
    up = classify_regime(mk_bars(10000 + t * 5, spread=10), P)
    assert up.regime == Regime.TRENDING_UP
    dn = classify_regime(mk_bars(13000 - t * 5, spread=10), P)
    assert dn.regime == Regime.TRENDING_DOWN


def test_regime_sideways_is_range_chop():
    t = np.arange(70, dtype=float)
    r = classify_regime(mk_bars(10000 + np.sin(t / 2.0) * 15, spread=10), P)
    assert r.regime == Regime.RANGE_CHOP


def test_regime_high_volatility():
    t = np.arange(70, dtype=float)
    r = classify_regime(mk_bars(10000 + t * 10, spread=150), P)
    assert r.regime == Regime.HIGH_VOLATILITY and r.atr_pct > P.high_vol_atr_pct


def test_regime_insufficient_data():
    r = classify_regime(mk_bars([10000 + i for i in range(20)]), P)
    assert r.regime == Regime.INSUFFICIENT_DATA and "need" in r.reasons[0]


def test_regime_contradictory_signals_are_not_a_trend():
    # EMAs stacked bullish but price pulled below VWAP (heavy early volume at higher prices)
    closes = list(np.linspace(10200, 10100, 12)) + list(np.linspace(9900.0, 10060.0, 58))
    vols = [50_000] * 12 + [200] * 58
    r = classify_regime(mk_bars(closes, vols, spread=10), P)
    assert r.ema_fast > r.ema_mid > r.ema_slow and r.close < r.vwap  # construct sanity
    assert r.regime == Regime.RANGE_CHOP


def test_no_volume_makes_vwap_unavailable_and_regime_unclassified():
    r = classify_regime(mk_bars(10000 + np.arange(70) * 5, vols=[0] * 70, spread=10), P)
    assert r.regime == Regime.INSUFFICIENT_DATA and "VWAP unavailable" in r.reasons[0]


_ = (ProviderHealth, IST, datetime)


def test_tick_a_few_seconds_newer_than_the_evaluation_clock_is_still_fresh(base):
    """A pass over 200+ names takes a while, so a tick can land just after the pass's clock was read."""
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap.model_copy(update={"last_tick_ts": snap.now + timedelta(seconds=8)}))
    assert "tick_fresh" not in reasons(ev)


def test_tick_far_in_the_future_still_fails_closed(base):
    eng, und, snap = base
    ev = evaluate_with(eng, und, snap.model_copy(update={"last_tick_ts": snap.now + timedelta(seconds=120)}))
    assert ev.decision == "NO_TRADE" and ("tick_fresh" in reasons(ev) or "clock_skew" in reasons(ev))
