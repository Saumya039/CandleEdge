"""Costs, slippage, position sizing and application-level risk safeguards (paper engine only).

Safeguards stop NEW paper entries. They never touch real brokerage positions."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from .config import CostModel, RiskSettings
from .models import IST


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""


def slippage_per_unit(price: float, tick: float, cost: CostModel) -> float:
    s = max(cost.slippage_ticks * tick, price * cost.slippage_pct / 100.0)
    return math.ceil(s / tick - 1e-9) * tick


def buy_fill(ask: float, tick: float, cost: CostModel) -> float:
    return round(ask + slippage_per_unit(ask, tick, cost), 2)


def sell_fill(bid: float | None, tick: float, cost: CostModel) -> float:
    b = bid if bid and bid > 0 else tick
    return round(max(b - slippage_per_unit(b, tick, cost), tick), 2)


def leg_costs(value: float, is_sell: bool, cost: CostModel) -> float:
    """Estimated charges for ONE order leg with premium turnover `value` (rupees)."""
    brokerage = cost.brokerage_per_order
    exch = value * cost.exchange_txn_pct / 100.0
    sebi = value * cost.sebi_pct / 100.0
    gst = (brokerage + exch + sebi) * cost.gst_pct / 100.0
    stt = value * cost.stt_sell_pct / 100.0 if is_sell else 0.0
    stamp = 0.0 if is_sell else value * cost.stamp_buy_pct / 100.0
    return brokerage + exch + sebi + gst + stt + stamp


def round_trip_costs(entry: float, exit_: float, qty: int, cost: CostModel) -> float:
    return leg_costs(entry * qty, False, cost) + leg_costs(exit_ * qty, True, cost)


class Sizing(BaseModel):
    lots: int
    per_lot_risk: float  # rupees: loss at the premium stop incl. exit slippage and estimated costs
    per_lot_premium: float
    reason: str = ""


def size_position(entry_fill: float, stop_premium: float, lot_size: int, tick: float, cost: CostModel,
                  risk: RiskSettings) -> Sizing:
    exit_fill = sell_fill(stop_premium, tick, cost)
    loss_units = max(entry_fill - exit_fill, 0.0)
    per_lot_risk = loss_units * lot_size + round_trip_costs(entry_fill, exit_fill, lot_size, cost)
    per_lot_premium = entry_fill * lot_size
    if not risk.confirmed:
        return Sizing(lots=0, per_lot_risk=per_lot_risk, per_lot_premium=per_lot_premium,
                      reason="Risk settings not confirmed by the user")
    if stop_premium >= entry_fill or per_lot_risk <= 0:
        return Sizing(lots=0, per_lot_risk=per_lot_risk, per_lot_premium=per_lot_premium,
                      reason="Risk per lot is not positive: stop is not below entry")
    by_risk = math.floor(risk.max_risk_per_trade / per_lot_risk)
    by_premium = math.floor(risk.max_premium_deployed / per_lot_premium)
    if by_risk < 1:
        return Sizing(lots=0, per_lot_risk=per_lot_risk, per_lot_premium=per_lot_premium,
                      reason=f"Minimum lot exceeds risk budget (1 lot risks ~Rs {per_lot_risk:,.0f} > "
                             f"Rs {risk.max_risk_per_trade:,.0f})")
    if by_premium < 1:
        return Sizing(lots=0, per_lot_risk=per_lot_risk, per_lot_premium=per_lot_premium,
                      reason="Minimum lot exceeds max premium deployed")
    return Sizing(lots=min(by_risk, by_premium), per_lot_risk=per_lot_risk, per_lot_premium=per_lot_premium)


class RiskState(BaseModel):
    day: str = ""
    realized_net: float = 0.0
    unrealized: float = 0.0
    trades_today: int = 0
    open_positions: int = 0
    consecutive_losses: int = 0
    cooldown_until: datetime | None = None
    paused: bool = False
    pause_reason: str = ""
    events: list[str] = Field(default_factory=list)


def risk_gate(now: datetime, state: RiskState, s: RiskSettings, cutoff_dt: datetime | None = None) -> list[Check]:
    now = now.astimezone(IST)
    cutoff_dt = cutoff_dt or datetime.combine(now.date(), s.trading_cutoff, IST)
    day_pnl = state.realized_net + state.unrealized
    out = [
        Check(name="risk_settings_confirmed", passed=s.confirmed,
              detail="User has confirmed risk settings" if s.confirmed else "Confirm risk settings to enable sizing"),
        Check(name="paper_enabled", passed=s.paper_enabled, detail="Paper engine enabled" if s.paper_enabled else "Paper engine disabled"),
        Check(name="not_paused", passed=not state.paused,
              detail="Trading not paused" if not state.paused else f"Global pause active: {state.pause_reason}"),
        Check(name="daily_loss_limit", passed=day_pnl > -s.max_daily_loss,
              detail=f"Day P&L Rs {day_pnl:,.0f} vs limit -Rs {s.max_daily_loss:,.0f}"),
        Check(name="max_trades", passed=state.trades_today < s.max_trades_per_session,
              detail=f"{state.trades_today}/{s.max_trades_per_session} trades"),
        Check(name="max_open_positions", passed=state.open_positions < s.max_open_positions,
              detail=f"{state.open_positions}/{s.max_open_positions} open"),
        Check(name="cooldown", passed=not (state.cooldown_until and now < state.cooldown_until),
              detail="No cooldown" if not (state.cooldown_until and now < state.cooldown_until)
              else f"Cooldown until {state.cooldown_until:%H:%M} IST after {state.consecutive_losses} losses"),
        Check(name="before_cutoff", passed=now < cutoff_dt,
              detail=f"Cutoff {cutoff_dt:%H:%M} IST"),
    ]
    return out


def register_close(state: RiskState, net_pnl: float, now: datetime, s: RiskSettings) -> None:
    state.realized_net += net_pnl
    state.open_positions = max(state.open_positions - 1, 0)
    if net_pnl < 0:
        state.consecutive_losses += 1
        if state.consecutive_losses >= s.cooldown_after_losses:
            state.cooldown_until = now + timedelta(minutes=s.cooldown_minutes)
            state.events.append(f"Cooldown started after {state.consecutive_losses} consecutive losses")
    else:
        state.consecutive_losses = 0
