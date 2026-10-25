"""Persistence: signals, paper trades, candles, health and audit events, strategy versions.

SQLAlchemy 2.x; SQLite by default, PostgreSQL via DATABASE_URL. Schema is managed by Alembic migrations
(`alembic upgrade head`); `create_all` is used only for ephemeral test databases."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import StrategyParams
from .models import Candle


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    underlying: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64), index=True)
    data_status: Mapped[str] = mapped_column(String(16))
    regime: Mapped[str] = mapped_column(String(24), default="")
    payload: Mapped[dict] = mapped_column(JSON)  # full signal snapshot: inputs, indicators, plan, transitions


class PaperTradeRow(Base):
    __tablename__ = "paper_trades"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    underlying: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(8))
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    est_costs: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    origin: Mapped[str] = mapped_column(String(16), default="PAPER")  # PAPER | BACKTEST
    payload: Mapped[dict] = mapped_column(JSON)


class CandleRow(Base):
    __tablename__ = "candles"
    instrument_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(8))


class HealthEventRow(Base):
    __tablename__ = "health_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(500))


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[dict] = mapped_column(JSON)


class StrategyVersionRow(Base):
    __tablename__ = "strategy_versions"
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    params: Mapped[dict] = mapped_column(JSON)


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


class Journal:
    def __init__(self, url: str = "sqlite://", create_tables: bool = False):
        kw: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kw["poolclass"] = StaticPool
        self.engine = create_engine(url, future=True, **kw)
        if create_tables:
            Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    # -- writers -----------------------------------------------------------------------------------
    def save_signal(self, sig, regime: str = "", data_status: str = "") -> None:
        row = SignalRow(
            id=sig.id, session_date=sig.created_ts.date().isoformat(), created_ts=sig.created_ts,
            updated_ts=sig.updated_ts, underlying=sig.underlying, direction=sig.direction.value,
            state=sig.state.value, strategy_version=sig.strategy_version, data_status=data_status, regime=regime,
            payload=_jsonable(sig.model_dump(mode="json")),
        )
        with self.Session.begin() as s:
            s.merge(row)

    def save_trade(self, t, origin: str = "PAPER") -> None:
        row = PaperTradeRow(
            id=t.id, signal_id=t.signal_id, session_date=t.entry_ts.date().isoformat(), entry_ts=t.entry_ts,
            exit_ts=t.exit_ts, underlying=t.underlying, status=t.status.value, gross_pnl=t.gross_pnl,
            est_costs=t.est_costs, net_pnl=t.net_pnl, origin=origin, payload=_jsonable(t.model_dump(mode="json")),
        )
        with self.Session.begin() as s:
            s.merge(row)

    def save_candle(self, c: Candle) -> None:
        with self.Session.begin() as s:
            s.merge(CandleRow(instrument_id=c.instrument_id, timeframe=c.timeframe, ts=c.ts, open=c.open, high=c.high,
                              low=c.low, close=c.close, volume=c.volume, source=c.source, quality=c.quality))

    def health_event(self, ts: datetime, kind: str, detail: str) -> None:
        with self.Session.begin() as s:
            s.add(HealthEventRow(ts=ts, session_date=ts.date().isoformat(), kind=kind, detail=detail[:500]))

    def audit(self, ts: datetime, kind: str, detail: dict) -> None:
        with self.Session.begin() as s:
            s.add(AuditEventRow(ts=ts, kind=kind, detail=_jsonable(detail)))

    def register_strategy(self, p: StrategyParams, ts: datetime) -> None:
        with self.Session.begin() as s:
            if s.get(StrategyVersionRow, p.version) is None:
                s.add(StrategyVersionRow(version=p.version, first_seen=ts, params=_jsonable(p.model_dump())))

    # -- readers -----------------------------------------------------------------------------------
    def signals(self, session_date: str | None = None, limit: int = 200) -> list[dict]:
        with self.Session() as s:
            q = select(SignalRow).order_by(SignalRow.created_ts.desc()).limit(limit)
            if session_date:
                q = q.where(SignalRow.session_date == session_date)
            return [r.payload for r in s.scalars(q)]

    def trades(self, session_date: str | None = None, origin: str | None = "PAPER", limit: int = 500) -> list[dict]:
        with self.Session() as s:
            q = select(PaperTradeRow).order_by(PaperTradeRow.entry_ts.desc()).limit(limit)
            if session_date:
                q = q.where(PaperTradeRow.session_date == session_date)
            if origin:
                q = q.where(PaperTradeRow.origin == origin)
            return [r.payload for r in s.scalars(q)]

    def health_events(self, session_date: str | None = None, limit: int = 200) -> list[dict]:
        with self.Session() as s:
            q = select(HealthEventRow).order_by(HealthEventRow.ts.desc()).limit(limit)
            if session_date:
                q = q.where(HealthEventRow.session_date == session_date)
            return [{"ts": r.ts.isoformat(), "kind": r.kind, "detail": r.detail} for r in s.scalars(q)]

    def audit_events(self, limit: int = 200) -> list[dict]:
        with self.Session() as s:
            q = select(AuditEventRow).order_by(AuditEventRow.ts.desc()).limit(limit)
            return [{"ts": r.ts.isoformat(), "kind": r.kind, "detail": r.detail} for r in s.scalars(q)]
