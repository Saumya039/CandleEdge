from datetime import datetime, timedelta

import pytest

from stratagy.models import IST, Direction, SignalState
from stratagy.statemachine import ALLOWED, TERMINAL, apply_event, new_signal
from stratagy.strategy import Evaluation, RegimeResult, TradePlan
from tests.test_risk_contracts_state import mkq

NOW = datetime(2026, 10, 26, 11, 0, tzinfo=IST)
S = SignalState


def make_signal():
    q = mkq(100)
    plan = TradePlan(
        direction=Direction.CALL, underlying="X", contract=q.instrument, quote=q, trigger_type="BREAKOUT", trigger_level=100,
        entry_zone_underlying=(100, 101), entry_ref_underlying=101, invalidation_underlying=98, target1_underlying=106,
        target2_underlying=110, stop_method="m", target_method="t", atr=2, delta_used=0.5, delta_source="estimated",
        entry_premium_assumed=100.25, premium_stop=90, premium_target1=110, premium_target2=120, premium_entry_limit=101,
        spread_pct=1, lot_size=75, lots=2, per_lot_risk=1000, per_lot_reward_t1=2000, rr_t1=2, rr_t2=3,
        est_costs_round_trip_per_lot=80, time_stop=NOW + timedelta(hours=1))
    ev = Evaluation(underlying="X", ts=NOW, strategy_version="v", trigger_tf="5m", decision="CANDIDATE", direction=Direction.CALL,
                    regime=RegimeResult(regime="TRENDING_UP"), plan=plan, trigger_bar_ts=NOW)
    return new_signal(ev, "sig-1", NOW)


def test_new_signal_starts_as_candidate_with_recorded_transition():
    s = make_signal()
    assert s.state == S.CANDIDATE
    assert [t.to_state for t in s.transitions] == [S.CANDIDATE]
    assert s.transitions[0].from_state == S.WATCHING


def test_happy_path_and_idempotency():
    s = make_signal()
    assert apply_event(s, "trigger", S.TRIGGERED, NOW, "in zone") is True
    for _ in range(5):  # repeated ticks re-raise the same event
        assert apply_event(s, "trigger", S.TRIGGERED, NOW, "in zone") is False
    assert apply_event(s, "t1", S.TARGET_1, NOW, "t1") is True
    assert apply_event(s, "t2", S.TARGET_2, NOW, "t2") is True
    assert s.closed and s.terminal
    n = len(s.transitions)
    assert apply_event(s, "stop", S.STOPPED, NOW, "late stop") is False  # terminal absorbs everything
    assert len(s.transitions) == n


def test_illegal_transitions_rejected():
    s = make_signal()
    assert apply_event(s, "stop", S.STOPPED, NOW, "stop before entry") is False  # CANDIDATE cannot be STOPPED
    assert apply_event(s, "t1", S.TARGET_1, NOW, "t1 before entry") is False
    assert s.state == S.CANDIDATE


@pytest.mark.parametrize("to", [S.INVALIDATED, S.EXPIRED])
def test_candidate_can_end_without_trigger(to):
    s = make_signal()
    assert apply_event(s, "end", to, NOW, "r")
    assert s.closed and s.state in TERMINAL


def test_table_has_no_exit_from_terminal_states():
    assert all(ALLOWED[t] == set() for t in TERMINAL)
    assert ALLOWED[S.TARGET_1] == {S.TARGET_2, S.STOPPED, S.TIME_EXIT}
