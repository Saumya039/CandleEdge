"""Exchange calendar and intraday session phases (Asia/Kolkata only; never server-local time)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from .config import SessionConfig
from .models import IST, MarketSession


class SessionPhase(StrEnum):
    CLOSED = "CLOSED"  # holiday, weekend, or outside pre-open..close window
    PRE_MARKET = "PRE_MARKET"
    OPENING_RANGE = "OPENING_RANGE"  # open until opening range is formed: no entry signals
    TRADING = "TRADING"
    NO_NEW_ENTRIES = "NO_NEW_ENTRIES"  # cutoff reached, market still open
    POST_CLOSE = "POST_CLOSE"


class SpecialSession(BaseModel):
    date: date
    open: time
    close: time
    note: str = ""


class CalendarFile(BaseModel):
    holidays: list[date] = Field(default_factory=list)
    special_sessions: list[SpecialSession] = Field(default_factory=list)


class ExchangeCalendar:
    """Weekday-only unless a user-maintained calendar file is present. Holidays are NOT hard-coded: when no
    calendar file exists `calendar_verified` is False and the UI shows a warning."""

    def __init__(self, cfg: SessionConfig | None = None, cal: CalendarFile | None = None, verified: bool = False):
        self.cfg = cfg or SessionConfig()
        self.cal = cal or CalendarFile()
        self.verified = verified

    @classmethod
    def from_file(cls, path: str | Path, cfg: SessionConfig | None = None) -> ExchangeCalendar:
        p = Path(path)
        if not p.exists():
            return cls(cfg, CalendarFile(), verified=False)
        return cls(cfg, CalendarFile.model_validate(json.loads(p.read_text())), verified=True)

    def session_for(self, d: date) -> MarketSession:
        special = next((s for s in self.cal.special_sessions if s.date == d), None)
        if special:
            return MarketSession(
                date=d,
                open=datetime.combine(d, special.open, IST),
                close=datetime.combine(d, special.close, IST),
                is_trading_day=True,
                note=f"Special session: {special.note}".strip(),
                calendar_verified=self.verified,
            )
        if d.weekday() >= 5:
            return MarketSession(date=d, open=None, close=None, is_trading_day=False, note="Weekend",
                                 calendar_verified=self.verified)
        if d in self.cal.holidays:
            return MarketSession(date=d, open=None, close=None, is_trading_day=False,
                                 note="Exchange holiday (from calendar file)", calendar_verified=self.verified)
        note = "" if self.verified else "Calendar file not configured: exchange holidays are unknown"
        return MarketSession(
            date=d,
            open=datetime.combine(d, self.cfg.open, IST),
            close=datetime.combine(d, self.cfg.close, IST),
            is_trading_day=True,
            note=note,
            calendar_verified=self.verified,
        )

    def phase(self, now: datetime, or_minutes: int, cutoff: time) -> SessionPhase:
        if now.tzinfo is None:
            raise ValueError("naive datetime not allowed")
        now = now.astimezone(IST)
        s = self.session_for(now.date())
        if not s.is_trading_day or s.open is None or s.close is None:
            return SessionPhase.CLOSED
        lead = datetime.combine(now.date(), self.cfg.open) - datetime.combine(now.date(), self.cfg.pre_open)
        pre = s.open - lead  # pre-open window length is kept for special sessions
        if now < pre:
            return SessionPhase.CLOSED
        if now < s.open:
            return SessionPhase.PRE_MARKET
        if now >= s.close:
            return SessionPhase.POST_CLOSE
        if now < s.open + timedelta(minutes=or_minutes):
            return SessionPhase.OPENING_RANGE
        if now >= self.offset_time(now.date(), cutoff):
            return SessionPhase.NO_NEW_ENTRIES
        return SessionPhase.TRADING

    def offset_time(self, d: date, t: time) -> datetime:
        """Translate a standard-session wall time (e.g. the 15:15 cutoff) to the session actually running on `d`,
        keeping its distance from the close, so special/shifted sessions get proportional cutoffs."""
        s = self.session_for(d)
        std_close = datetime.combine(d, self.cfg.close, IST)
        if s.close is None:
            return datetime.combine(d, t, IST)
        return s.close - (std_close - datetime.combine(d, t, IST))

    def next_open(self, now: datetime) -> datetime | None:
        d = now.astimezone(IST).date()
        for i in range(0, 15):
            s = self.session_for(d + timedelta(days=i))
            if s.is_trading_day and s.open and s.open > now:
                return s.open
        return None
