from datetime import date, datetime, timedelta

import pytest

from stratagy.config import ContractParams, CostModel, RiskSettings
from stratagy.contracts import choose_expiry, select_contract
from stratagy.models import (
    IST,
    DataStatus,
    Direction,
    Greeks,
    Instrument,
    InstrumentKind,
    OptionChainRow,
    OptionChainSnapshot,
    OptionQuote,
    OptionType,
)
from stratagy.risk import (
    RiskState,
    buy_fill,
    leg_costs,
    register_close,
    risk_gate,
    round_trip_costs,
    sell_fill,
    size_position,
    slippage_per_unit,
)

NOW = datetime(2026, 10, 26, 11, 0, tzinfo=IST)
COST = CostModel()


# ---------------------------------------------------------------- risk sizing
def test_slippage_is_larger_of_ticks_and_pct_rounded_up_to_tick():
    assert slippage_per_unit(100.0, 0.05, COST) == pytest.approx(0.25)  # pct (0.25) > 2 ticks (0.10)
    assert slippage_per_unit(10.0, 0.05, COST) == pytest.approx(0.10)  # ticks win
    assert buy_fill(100.0, 0.05, COST) == pytest.approx(100.25)
    assert sell_fill(100.0, 0.05, COST) == pytest.approx(99.75)
    assert sell_fill(None, 0.05, COST) >= 0.05  # no bid: floor at one tick, never negative


def test_costs_are_itemised_and_positive():
    buy = leg_costs(100_000, False, COST)
    sell = leg_costs(100_000, True, COST)
    assert buy > 20 and sell > buy  # sell carries STT
    assert round_trip_costs(100, 110, 1000, COST) == pytest.approx(leg_costs(100_000, False, COST) + leg_costs(110_000, True, COST))


def test_sizing_requires_confirmation():
    r = RiskSettings(confirmed=False)
    s = size_position(100.0, 80.0, 75, 0.05, COST, r)
    assert s.lots == 0 and "not confirmed" in s.reason


def test_sizing_respects_risk_budget_and_lot_size():
    r = RiskSettings(confirmed=True, max_risk_per_trade=10_000, max_premium_deployed=10_000_000)
    s = size_position(100.0, 90.0, 75, 0.05, COST, r)
    # per-lot risk = (100.25 -> sell 89.75..): positive, lots = floor(budget / per_lot_risk)
    assert s.lots == int(10_000 // s.per_lot_risk) and s.lots >= 1
    assert s.lots * s.per_lot_risk <= 10_000


def test_single_lot_exceeding_risk_budget_is_no_trade_not_a_violation():
    r = RiskSettings(confirmed=True, max_risk_per_trade=500)
    s = size_position(300.0, 200.0, 75, 0.05, COST, r)
    assert s.lots == 0 and "Minimum lot exceeds risk budget" in s.reason


def test_premium_cap_limits_lots():
    r = RiskSettings(confirmed=True, max_risk_per_trade=1e9, max_premium_deployed=2 * 100.25 * 75 + 1)
    s = size_position(100.0, 90.0, 75, 0.05, COST, r)
    assert s.lots == 2


def test_stop_not_below_entry_is_refused():
    r = RiskSettings(confirmed=True)
    assert size_position(100.0, 130.0, 75, 0.05, COST, r).lots == 0


# ---------------------------------------------------------------- risk gate
def failed(checks):
    return {c.name for c in checks if not c.passed}


def test_gate_all_clear():
    assert failed(risk_gate(NOW, RiskState(), RiskSettings(confirmed=True))) == set()


def test_gate_blocks_each_limit():
    s = RiskSettings(confirmed=True, max_daily_loss=5000, max_trades_per_session=2, max_open_positions=1)
    assert "daily_loss_limit" in failed(risk_gate(NOW, RiskState(realized_net=-5000), s))
    assert "daily_loss_limit" in failed(risk_gate(NOW, RiskState(realized_net=-3000, unrealized=-2500), s))  # MTM counts
    assert "max_trades" in failed(risk_gate(NOW, RiskState(trades_today=2), s))
    assert "max_open_positions" in failed(risk_gate(NOW, RiskState(open_positions=1), s))
    assert "not_paused" in failed(risk_gate(NOW, RiskState(paused=True, pause_reason="x"), s))
    assert "risk_settings_confirmed" in failed(risk_gate(NOW, RiskState(), RiskSettings(confirmed=False)))
    late = NOW.replace(hour=15, minute=16)
    assert "before_cutoff" in failed(risk_gate(late, RiskState(), s))
    assert "cooldown" in failed(risk_gate(NOW, RiskState(cooldown_until=NOW + timedelta(minutes=5), consecutive_losses=2), s))
    assert "cooldown" not in failed(risk_gate(NOW + timedelta(minutes=6), RiskState(cooldown_until=NOW + timedelta(minutes=5)), s))


def test_cooldown_after_consecutive_losses_and_reset_on_win():
    s = RiskSettings(confirmed=True, cooldown_after_losses=2, cooldown_minutes=30)
    st = RiskState(open_positions=1)
    register_close(st, -100, NOW, s)
    assert st.cooldown_until is None and st.consecutive_losses == 1
    st.open_positions = 1
    register_close(st, -100, NOW, s)
    assert st.cooldown_until == NOW + timedelta(minutes=30)
    st.open_positions = 1
    register_close(st, 50, NOW, s)
    assert st.consecutive_losses == 0 and st.open_positions == 0


# ---------------------------------------------------------------- contracts
def mkq(strike, kind=OptionType.CE, bid=99.0, ask=100.0, vol=5000, oi=50000, delta=0.55, age=1.0, tradable=True, lot=75, with_delta=True):
    inst = Instrument(id=f"X{strike}{kind.value}", exchange="SIM", symbol=f"X{strike}{kind.value}", underlying="X",
                      kind=InstrumentKind.OPTION, expiry=date(2026, 11, 3), strike=strike, option_type=kind, lot_size=lot,
                      tick_size=0.05, tradable=tradable)
    g = Greeks(delta=delta if kind == OptionType.CE else -delta, iv=0.15, source="estimated") if with_delta else None
    return OptionQuote(instrument=inst, ltp=99.5, bid=bid, ask=ask, volume=vol, oi=oi, greeks=g,
                       ts=NOW - timedelta(seconds=age), received_ts=NOW - timedelta(seconds=age), status=DataStatus.SIMULATED)


def chain(*quotes):
    return OptionChainSnapshot(underlying="X", expiry=date(2026, 11, 3), expiries=[date(2026, 11, 3)], forward=100.0,
                               rows=[OptionChainRow(strike=q.instrument.strike, ce=q if q.instrument.option_type == OptionType.CE else None,
                                                    pe=q if q.instrument.option_type == OptionType.PE else None) for q in quotes],
                               ts=NOW, received_ts=NOW, status=DataStatus.SIMULATED, source="t")


P = ContractParams()


def test_expiry_choice_skips_near_expiry():
    exps = [date(2026, 10, 26), date(2026, 10, 29), date(2026, 11, 5)]
    assert choose_expiry(exps, date(2026, 10, 26), P) == date(2026, 10, 29)
    assert choose_expiry([date(2026, 10, 26)], date(2026, 10, 26), P) is None


def test_selects_tightest_spread_then_closest_delta():
    wide = mkq(100, bid=95, ask=100)  # ~5% spread
    ok1 = mkq(105, bid=99.5, ask=100, delta=0.45)
    ok2 = mkq(110, bid=99.5, ask=100, delta=0.56)
    pick = select_contract(chain(wide, ok1, ok2), Direction.CALL, NOW, P)
    assert pick.quote.instrument.strike == 110
    assert pick.rejected["spread too wide"] == 1


@pytest.mark.parametrize("kw,reason", [
    (dict(age=60.0), "stale quote"),
    (dict(vol=10), "volume too low"),
    (dict(vol=None), "volume unavailable"),
    (dict(oi=10), "open interest too low"),
    (dict(delta=0.1), "delta outside range"),
    (dict(with_delta=False), "delta unavailable"),
    (dict(bid=None), "no two-sided quote"),
    (dict(tradable=False), "not tradable"),
])
def test_each_rejection_reason(kw, reason):
    pick = select_contract(chain(mkq(100, **kw)), Direction.CALL, NOW, P)
    assert pick.quote is None and pick.rejected.get(reason) == 1


def test_put_selection_uses_pe_rows_and_absolute_delta():
    pe = mkq(100, OptionType.PE, delta=0.5)
    pick = select_contract(chain(mkq(100, OptionType.CE), pe), Direction.PUT, NOW, P)
    assert pick.quote.instrument.option_type == OptionType.PE
