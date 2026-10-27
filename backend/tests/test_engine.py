"""Engine lifecycle, feed failure handling, safeguards, journal and the 'no live orders' guarantee."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from pathlib import Path

import pytest

from stratagy.config import RiskSettings, Settings
from stratagy.journal import Journal
from stratagy.models import Direction, SignalState
from stratagy.paper import TradeStatus
from stratagy.statemachine import ALLOWED
from tests.conftest import new_engine, run_until

PKG = Path(__file__).resolve().parent.parent / "stratagy"


def full_day(seed, risk=None, journal=None):
    eng, prov = new_engine(seed, risk, journal)
    asyncio.run(run_until(eng, prov, lambda e: False))
    return eng, prov


@pytest.fixture(scope="module")
def day5():
    return full_day(1, journal=Journal("sqlite://", create_tables=True))


def test_signal_lifecycle_follows_the_state_machine(day5):
    eng, _ = day5
    assert eng.signals
    for sig in eng.signals.values():
        assert sig.transitions[0].from_state == SignalState.WATCHING
        for a, b in zip(sig.transitions, sig.transitions[1:], strict=False):
            assert b.to_state in ALLOWED[a.to_state]
        assert len({t.event_id for t in sig.transitions}) == len(sig.transitions)  # no duplicate events
        assert sig.closed  # everything is resolved by the close


def test_at_most_one_paper_trade_per_signal_and_conservative_fills(day5):
    eng, _ = day5
    assert len(eng.trades) <= len(eng.signals)
    for t in eng.trades.values():
        sig = eng.signals[t.signal_id]
        assert t.status == TradeStatus.CLOSED and t.lots_open == 0
        assert t.fills[0].side == "BUY" and all(f.simulated for f in t.fills)
        assert t.entry_fill >= sig.plan.quote.ask  # ask + slippage, never better than the quote
        assert t.est_costs > 0 and t.net_pnl == pytest.approx(t.gross_pnl - t.est_costs)
        assert "no broker order was sent" in t.data_label
        assert sum(f.lots for f in t.fills if f.side == "SELL") == t.lots


def test_repeated_processing_without_new_time_creates_nothing(day5):
    eng, _ = day5
    n_sig, n_tr, n_alert = len(eng.signals), len(eng.trades), len(eng.alerts)
    for _ in range(5):
        asyncio.run(eng.process())
    assert (len(eng.signals), len(eng.trades), len(eng.alerts)) == (n_sig, n_tr, n_alert)


def test_session_close_produces_report_and_empty_book(day5):
    eng, _ = day5
    rep = eng.session_report
    assert rep and rep["data_label"] == "SIMULATED" and rep["origin"] == "PAPER"
    assert rep["summary"]["setups_generated"] == len(eng.signals)
    assert rep["summary"]["open_trades"] == 0 and not eng.open_trades()
    assert "not a forecast" in rep["disclaimer"] or "forecast" in rep["disclaimer"]
    assert eng.risk_state.open_positions == 0


def test_journal_persists_signals_trades_candles_and_audit(day5):
    eng, _ = day5
    j = eng.journal
    assert len(j.signals()) == len(eng.signals)
    assert len(j.trades()) == len(eng.trades)
    kinds = {a["kind"] for a in j.audit_events()}
    assert {"engine_start", "signal_transition", "session_closed"} <= kinds
    snap = j.signals()[0]
    assert snap["strategy_version"] and snap["indicators"] and snap["plan"]["invalidation_underlying"]  # reconstructable


def test_no_new_signals_after_cutoff(day5):
    eng, _ = day5
    for sig in eng.signals.values():
        assert sig.created_ts.time() < eng.risk.trading_cutoff
        if sig.trigger_ts:
            assert sig.trigger_ts.time() < eng.risk.trading_cutoff


# ------------------------------------------------------------------ feed failure
def test_feed_outage_suppresses_signals_then_recovers_without_duplicates():
    eng, prov = new_engine(1)

    async def go():
        await eng.start()
        await run_until(eng, prov, lambda e: prov.now().hour == 9 and prov.now().minute >= 25)
        n_before = len(eng.signals)
        assert not eng.is_stale(prov.now())
        prov.inject_outage(15 * 60)  # covers the 09:30 signal in the unperturbed run
        for _ in range(6 * 6):  # 6 minutes of 10s steps
            prov.advance(10)
            await eng.process()
        assert eng.is_stale(prov.now())
        assert any(h["kind"] == "stale" for h in eng.health_log)
        ev = eng.u["BANKNIFTY"].latest_eval
        assert ev.decision == "NO_TRADE" and "tick_fresh" in " ".join(ev.reasons)
        assert len(eng.signals) == n_before  # fail closed: nothing created while stale
        for _ in range(6 * 14):
            prov.advance(10)
            await eng.process()
        assert not eng.is_stale(prov.now())
        assert any(h["kind"] == "recovered" for h in eng.health_log)
        # the outage left a hole in 1m candles: it must remain a hole, never be back-filled
        cs = eng.u["BANKNIFTY"].builder.closed_list()
        minutes = [c.ts for c in cs if c.ts.date() == prov.now().date()]
        gaps = [b - a for a, b in zip(minutes, minutes[1:], strict=False) if b - a > timedelta(minutes=1)]
        assert gaps and max(gaps) >= timedelta(minutes=10)

    asyncio.run(go())


def test_pause_blocks_new_entries_and_is_audited():
    j = Journal("sqlite://", create_tables=True)
    eng, prov = new_engine(1, journal=j)

    async def go():
        await eng.start()
        eng.set_pause(True, "test", prov.now())
        await run_until(eng, prov, lambda e: False)

    asyncio.run(go())
    assert not eng.signals and not eng.trades
    assert any(a["kind"] == "pause" for a in j.audit_events())
    assert "not_paused" in " ".join(eng.u["BANKNIFTY"].latest_eval.reasons) or eng.u["BANKNIFTY"].latest_eval.decision == "NO_TRADE"


def test_unconfirmed_risk_settings_block_all_entries():
    eng, _ = full_day(1, risk=RiskSettings(confirmed=False))
    assert not eng.signals
    last = eng.u["BANKNIFTY"].latest_eval
    assert any(c.name == "risk_settings_confirmed" and not c.passed for c in last.checks)


def test_daily_loss_limit_stops_new_entries():
    eng, prov = new_engine(1)
    eng.risk_state.realized_net = -eng.risk.max_daily_loss
    asyncio.run(run_until(eng, prov, lambda e: False))
    assert not eng.signals


def test_risk_settings_changes_are_audited():
    j = Journal("sqlite://", create_tables=True)
    eng, prov = new_engine(1, journal=j)
    eng.set_risk(eng.risk.model_copy(update={"max_trades_per_session": 1}), prov.now())
    ev = [a for a in j.audit_events() if a["kind"] == "risk_settings_changed"]
    assert ev and ev[0]["detail"]["after"]["max_trades_per_session"] == 1


def _pre_trigger_candidate():
    """A genuine candidate (real evaluation) that has NOT yet been triggered, on an engine we can steer."""
    from stratagy.models import DataStatus  # noqa: F401
    from stratagy.statemachine import new_signal
    from tests.conftest import clean_gates, evaluate_with, first_signal_engine

    eng, prov = first_signal_engine(1)
    und = next(iter(eng.signals.values())).underlying
    ev = evaluate_with(eng, und, gates=clean_gates(eng, und))
    assert ev.decision == "CANDIDATE"
    eng.signals.clear()
    eng.trades.clear()
    eng.risk_state.open_positions = eng.risk_state.trades_today = 0
    sig = new_signal(ev, "sig-test", prov.now())
    eng.signals[sig.id] = sig
    return eng, prov, sig, und


def _manage(eng, sig, now=None):
    from stratagy.sessions import SessionPhase

    asyncio.run(eng._manage(sig, now or eng.provider.now(), SessionPhase.TRADING))


def test_candidate_expires_instead_of_chasing_when_price_leaves_zone():
    eng, prov, sig, und = _pre_trigger_candidate()
    lo, hi = sig.plan.entry_zone_underlying
    eng.u[und].last_ltp = (lo - 0.5 * sig.plan.atr) if sig.direction == Direction.PUT else (hi + 0.5 * sig.plan.atr)
    _manage(eng, sig)
    assert sig.state == SignalState.EXPIRED and "no chasing" in sig.transitions[-1].reason
    assert not eng.trades


def test_candidate_invalidated_before_entry_when_structure_breaks():
    eng, prov, sig, und = _pre_trigger_candidate()
    p = sig.plan
    eng.u[und].last_ltp = p.invalidation_underlying + (1 if sig.direction == Direction.PUT else -1)
    _manage(eng, sig)
    assert sig.state == SignalState.INVALIDATED and not eng.trades


def test_candidate_times_out_after_ttl_bars():
    eng, prov, sig, und = _pre_trigger_candidate()
    lo, hi = sig.plan.entry_zone_underlying
    eng.u[und].last_ltp = (lo + hi) / 2
    late = prov.now() + timedelta(minutes=5 * (eng.p.candidate_ttl_bars + 1))
    _manage(eng, sig, late)
    assert sig.state == SignalState.EXPIRED and "bars" in sig.transitions[-1].reason


def test_trigger_happens_once_and_uses_conservative_fill():
    eng, prov, sig, und = _pre_trigger_candidate()
    lo, hi = sig.plan.entry_zone_underlying
    eng.u[und].last_ltp = (lo + hi) / 2
    for _ in range(4):  # repeated ticks inside the zone
        _manage(eng, sig)
    assert sig.state == SignalState.TRIGGERED and len(eng.trades) == 1
    t = next(iter(eng.trades.values()))
    assert t.entry_fill >= t.fills[0].price - 1e-9 and eng.risk_state.trades_today == 1 and eng.risk_state.open_positions == 1


def test_trigger_blocked_by_risk_gate_expires_candidate():
    eng, prov, sig, und = _pre_trigger_candidate()
    lo, hi = sig.plan.entry_zone_underlying
    eng.u[und].last_ltp = (lo + hi) / 2
    eng.set_pause(True, "test", prov.now())
    _manage(eng, sig)
    assert sig.state == SignalState.EXPIRED and "risk safeguards" in sig.transitions[-1].reason and not eng.trades


def test_stop_and_square_off_exits_are_marked_with_reasons():
    eng, prov, sig, und = _pre_trigger_candidate()
    lo, hi = sig.plan.entry_zone_underlying
    eng.u[und].last_ltp = (lo + hi) / 2
    _manage(eng, sig)
    assert sig.state == SignalState.TRIGGERED
    eng.u[und].last_ltp = sig.plan.invalidation_underlying + (-1 if sig.direction == Direction.CALL else 1)
    _manage(eng, sig)
    assert sig.state == SignalState.STOPPED and sig.closed
    t = next(iter(eng.trades.values()))
    assert t.status == TradeStatus.CLOSED and "invalidation" in t.exit_reason
    assert eng.risk_state.open_positions == 0 and eng.risk_state.realized_net == pytest.approx(t.net_pnl)


# ------------------------------------------------------------------ live orders are impossible
def test_live_orders_disabled_by_default_and_no_order_code_exists():
    assert Settings().live_orders_enabled is False
    bad = re.compile(r"place_order|modify_order|cancel_order|/orders|order_place|\.place\(", re.I)
    for f in PKG.rglob("*.py"):
        assert not bad.search(f.read_text()), f"order-related call found in {f}"
    from stratagy.providers.kite import KiteProvider
    from stratagy.providers.simulator import SimulatorProvider

    assert KiteProvider.capabilities.order_api is False and SimulatorProvider.capabilities.order_api is False


def test_one_stale_name_does_not_flag_the_whole_feed_but_blocks_that_name():
    eng, prov = new_engine(1)

    async def go():
        await eng.start()
        await run_until(eng, prov, lambda e: prov.now().hour == 9 and prov.now().minute >= 25)
        now = prov.now()
        names = list(eng.u)
        assert len(names) >= 2
        eng.u[names[0]].last_tick_ts = now - timedelta(seconds=eng.dh.stale_after_s + 100)  # one illiquid name
        assert not eng.is_stale(now)  # others are fresh: feed is healthy
        for st in eng.u.values():
            st.last_tick_ts = now - timedelta(seconds=eng.dh.stale_after_s + 100)
        assert eng.is_stale(now)  # nothing fresh anywhere: fail closed

    asyncio.run(go())


def test_forming_bar_merges_open_bucket_and_never_enters_closed_series():
    from datetime import datetime

    from stratagy.candles import forming_bar
    from stratagy.models import IST, Candle

    def c(h, m, o, hi, lo, cl):
        return Candle(instrument_id="X", timeframe="1m", ts=datetime(2026, 10, 27, h, m, tzinfo=IST),
                      open=o, high=hi, low=lo, close=cl, volume=10, source="t")

    closed = [c(9, 15, 100, 102, 99, 101), c(9, 16, 101, 105, 100, 104)]
    cur = c(9, 17, 104, 106, 103, 105)
    f = forming_bar(closed, cur, "5m")
    assert f.ts == datetime(2026, 10, 27, 9, 15, tzinfo=IST)
    assert (f.open, f.high, f.low, f.close, f.volume) == (100, 106, 99, 105, 30)
    assert f.quality == "gap"  # only 3 of 5 minutes present: never presented as complete
    assert forming_bar(closed, None, "5m") is None
