"""Signal lifecycle: WATCHING -> CANDIDATE -> TRIGGERED -> INVALIDATED | TARGET_1 | TARGET_2 | STOPPED |
TIME_EXIT | EXPIRED, with idempotent event application.

Idempotency: every event carries a deterministic id (signal id + event kind). Re-applying an id, or any event
on a terminal signal, is a no-op that returns False, so repeated ticks cannot create duplicate transitions,
alerts or paper entries."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .models import Direction, SignalState
from .risk import Check
from .strategy import Evaluation, ScoreComponent, TradePlan

S = SignalState

ALLOWED: dict[SignalState, set[SignalState]] = {
    S.WATCHING: {S.CANDIDATE},
    S.CANDIDATE: {S.TRIGGERED, S.INVALIDATED, S.EXPIRED},
    S.TRIGGERED: {S.TARGET_1, S.TARGET_2, S.STOPPED, S.TIME_EXIT},
    S.TARGET_1: {S.TARGET_2, S.STOPPED, S.TIME_EXIT},
    S.INVALIDATED: set(), S.TARGET_2: set(), S.STOPPED: set(), S.TIME_EXIT: set(), S.EXPIRED: set(),
}
TERMINAL = {S.INVALIDATED, S.TARGET_2, S.STOPPED, S.TIME_EXIT, S.EXPIRED}


class Transition(BaseModel):
    ts: datetime
    from_state: SignalState
    to_state: SignalState
    event_id: str
    reason: str
    underlying_price: float | None = None
    premium: float | None = None


class Signal(BaseModel):
    id: str
    dedupe_key: str
    underlying: str
    direction: Direction
    state: SignalState = SignalState.WATCHING
    closed: bool = False  # True when no further management is needed (terminal, or T1 on a single lot)
    created_ts: datetime
    updated_ts: datetime
    created_bar_ts: datetime
    strategy_version: str
    trigger_tf: str
    plan: TradePlan
    score: float | None = None
    score_components: list[ScoreComponent] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    indicators: dict[str, float | None] = Field(default_factory=dict)
    levels: dict[str, float | None] = Field(default_factory=dict)
    data_sources: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    applied_events: list[str] = Field(default_factory=list)
    trigger_ts: datetime | None = None
    bars_since_trigger: int = 0
    bars_since_created: int = 0

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL


def new_signal(ev: Evaluation, signal_id: str, now: datetime) -> Signal:
    assert ev.plan and ev.direction and ev.trigger_bar_ts and ev.dedupe_key
    sig = Signal(
        id=signal_id, dedupe_key=ev.dedupe_key, underlying=ev.underlying, direction=ev.direction, created_ts=now,
        updated_ts=now, created_bar_ts=ev.trigger_bar_ts, strategy_version=ev.strategy_version,
        trigger_tf=ev.trigger_tf, plan=ev.plan, score=ev.score, score_components=ev.score_components,
        rationale=ev.reasons, checks=ev.checks, indicators=ev.indicators, levels=ev.levels,
        data_sources=ev.data_sources,
    )
    apply_event(sig, "created", S.CANDIDATE, now, "Setup conditions satisfied on closed candle")
    return sig


def apply_event(sig: Signal, kind: str, to: SignalState, ts: datetime, reason: str,
                price: float | None = None, premium: float | None = None) -> bool:
    """Returns True only if the signal actually changed state."""
    event_id = f"{sig.id}:{kind}"
    if event_id in sig.applied_events or sig.terminal or sig.closed:
        return False
    if to not in ALLOWED[sig.state]:
        return False
    sig.applied_events.append(event_id)
    sig.transitions.append(Transition(ts=ts, from_state=sig.state, to_state=to, event_id=event_id, reason=reason,
                                      underlying_price=price, premium=premium))
    sig.state = to
    sig.updated_ts = ts
    if to == S.TRIGGERED:
        sig.trigger_ts = ts
    if to in TERMINAL:
        sig.closed = True
    return True
