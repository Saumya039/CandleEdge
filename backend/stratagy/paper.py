"""Paper-trading engine. Simulated fills only; there is no broker or order code in this module.

Fill model (conservative, documented): buys fill at ask + slippage, sells fill at bid - slippage, where
slippage = max(slippage_ticks * tick, slippage_pct * price) rounded up to the tick. Stops are not guaranteed:
the exit fills at the current bid minus slippage even if that is below the stop level."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .config import CostModel
from .models import Direction, OptionQuote
from .risk import buy_fill, leg_costs, sell_fill


class TradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Fill(BaseModel):
    ts: datetime
    side: str  # BUY | SELL
    lots: int
    price: float
    reason: str
    simulated: bool = True


class PaperTrade(BaseModel):
    id: str
    signal_id: str
    underlying: str
    symbol: str
    direction: Direction
    strike: float
    option_type: str
    expiry: str
    lot_size: int
    lots: int
    lots_open: int
    status: TradeStatus = TradeStatus.OPEN
    entry_ts: datetime
    entry_fill: float
    fills: list[Fill] = Field(default_factory=list)
    premium_stop: float
    stop_moved_to_breakeven: bool = False
    gross_pnl: float = 0.0
    est_costs: float = 0.0
    net_pnl: float = 0.0
    mfe: float = 0.0  # max favourable / adverse excursion in rupees, on bid marks (data permitting)
    mae: float = 0.0
    exit_reason: str = ""
    exit_ts: datetime | None = None
    mark: float | None = None
    data_label: str = "PAPER (simulated fills; no broker order was sent)"
    data_status: str = ""
    cost_assumptions: dict[str, float] = Field(default_factory=dict)

    def unrealized(self) -> float:
        if self.status == TradeStatus.CLOSED or self.mark is None:
            return 0.0
        return (self.mark - self.entry_fill) * self.lot_size * self.lots_open


def open_trade(signal_id: str, trade_id: str, plan, quote: OptionQuote, lots: int, now: datetime, cost: CostModel) -> PaperTrade:
    inst = quote.instrument
    assert quote.ask is not None
    fill = buy_fill(quote.ask, inst.tick_size, cost)
    t = PaperTrade(
        id=trade_id, signal_id=signal_id, underlying=plan.underlying, symbol=inst.symbol, direction=plan.direction,
        strike=inst.strike or 0.0, option_type=inst.option_type.value if inst.option_type else "", expiry=str(inst.expiry),
        lot_size=inst.lot_size, lots=lots, lots_open=lots, entry_ts=now, entry_fill=fill, premium_stop=plan.premium_stop,
        data_status=quote.status.value, cost_assumptions=cost.model_dump(),
    )
    t.fills.append(Fill(ts=now, side="BUY", lots=lots, price=fill, reason="Entry trigger"))
    t.est_costs += leg_costs(fill * lots * inst.lot_size, False, cost)
    t.mark = quote.bid
    return t


def mark_trade(t: PaperTrade, quote: OptionQuote) -> None:
    if quote.bid is not None:
        t.mark = quote.bid
        pnl = (quote.bid - t.entry_fill) * t.lot_size * t.lots_open
        t.mfe = max(t.mfe, pnl)
        t.mae = min(t.mae, pnl)
    t.data_status = quote.status.value


def close_lots(t: PaperTrade, lots: int, quote: OptionQuote, now: datetime, reason: str, cost: CostModel) -> float:
    """Simulated sell of `lots`. Returns net P&L of this leg (gross minus estimated leg costs)."""
    lots = min(lots, t.lots_open)
    price = sell_fill(quote.bid, quote.instrument.tick_size, cost)
    qty = lots * t.lot_size
    gross = (price - t.entry_fill) * qty
    leg_c = leg_costs(price * qty, True, cost)
    t.fills.append(Fill(ts=now, side="SELL", lots=lots, price=price, reason=reason))
    t.gross_pnl += gross
    t.est_costs += leg_c
    t.lots_open -= lots
    t.net_pnl = t.gross_pnl - t.est_costs
    if t.lots_open == 0:
        t.status = TradeStatus.CLOSED
        t.exit_reason = reason
        t.exit_ts = now
        t.mark = None
    return gross - leg_c
