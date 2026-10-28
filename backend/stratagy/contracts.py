"""Option-contract selection: visible, configurable liquidity/freshness criteria."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from .config import ContractParams
from .models import IST, Direction, OptionChainSnapshot, OptionQuote, OptionType


class ContractChoice(BaseModel):
    quote: OptionQuote | None = None
    considered: int = 0
    rejected: dict[str, int] = Field(default_factory=dict)
    criteria: dict[str, float | int | str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def choose_expiry(expiries: list[date], today: date, p: ContractParams) -> date | None:
    """Earliest expiry with at least `min_days_to_expiry` calendar days left (near-expiry prices are less reliable)."""
    for e in sorted(expiries):
        if (e - today).days >= p.min_days_to_expiry:
            return e
    return None


def quote_age_s(q: OptionQuote, now: datetime) -> float:
    return (now.astimezone(IST) - q.received_ts.astimezone(IST)).total_seconds()


def select_contract(chain: OptionChainSnapshot, direction: Direction, now: datetime, p: ContractParams) -> ContractChoice:
    kind = OptionType.CE if direction == Direction.CALL else OptionType.PE
    out = ContractChoice(criteria={
        "type": kind.value, "max_spread_pct": p.max_spread_pct, "min_volume": p.min_volume,
        "delta_range": f"{p.delta_min:.2f}-{p.delta_max:.2f}", "delta_target": p.delta_target,
        "max_quote_age_s": p.max_quote_age_s, "min_days_to_expiry": p.min_days_to_expiry,
    })
    cands: list[tuple[float, float, OptionQuote]] = []

    def rej(why: str) -> None:
        out.rejected[why] = out.rejected.get(why, 0) + 1

    for row in chain.rows:
        q = row.ce if kind == OptionType.CE else row.pe
        if q is None:
            continue
        out.considered += 1
        if not q.instrument.tradable:
            rej("not tradable")
        elif q.instrument.lot_size < 1 or q.instrument.strike is None or q.instrument.expiry is None:
            rej("invalid contract metadata")
        elif q.bid is None or q.ask is None or q.spread is None:
            rej("no two-sided quote")
        elif quote_age_s(q, now) > p.max_quote_age_s:
            rej("stale quote")
        elif q.spread_pct is None or q.spread_pct > p.max_spread_pct:
            rej("spread too wide")
        elif q.volume is None:
            rej("volume unavailable")
        elif q.volume < p.min_volume:
            rej("volume too low")
        elif q.oi is not None and q.oi < p.min_oi:
            rej("open interest too low")
        elif q.greeks is None or q.greeks.delta is None:
            rej("delta unavailable")
        elif not (p.delta_min <= abs(q.greeks.delta) <= p.delta_max):
            rej("delta outside range")
        else:
            cands.append((q.spread_pct, abs(abs(q.greeks.delta) - p.delta_target), q))
    if not cands:
        out.notes.append("No contract passed the liquidity/freshness criteria")
        return out
    cands.sort(key=lambda t: (round(t[0], 2), t[1]))
    out.quote = cands[0][2]
    if out.quote.oi is None:
        out.notes.append("Open interest unavailable from provider: OI criterion skipped")
    return out
