"""Shared scenario helpers. Scenarios run the real engine on the seeded SIMULATOR until the first signal appears,
so every scenario test exercises the production code path (ticks -> candles -> strategy -> signal)."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from stratagy.config import DataHealthParams, RiskSettings
from stratagy.engine import Engine
from stratagy.providers.simulator import SimulatorProvider
from stratagy.sessions import ExchangeCalendar
from stratagy.strategy import Snapshot

SIM_DATE = date(2026, 10, 23)  # a Friday
PUT_SEED = 1  # BANKNIFTY BUY_PUT candidate at 09:30:10 on the pinned simulated day
CALL_SEED = None  # filled in by CALL_SEED discovery below (see tests/scenarios.py)


def new_engine(seed: int, risk: RiskSettings | None = None, journal=None, eval_interval_s: float = 30.0, **kw):
    prov = SimulatorProvider(seed=seed, sim_date=SIM_DATE)
    eng = Engine(prov, calendar=ExchangeCalendar(), risk=risk or RiskSettings(confirmed=True), journal=journal,
                 eval_interval_s=eval_interval_s, **kw)
    return eng, prov


async def run_until(eng: Engine, prov: SimulatorProvider, stop, step_s: float = 10.0, until_hhmm=(15, 45)):
    if not eng.started:
        await eng.start()
    end = prov.now().replace(hour=until_hhmm[0], minute=until_hhmm[1])
    while prov.now() < end and not stop(eng):
        prov.advance(step_s)
        await eng.process()


def first_signal_engine(seed: int, risk: RiskSettings | None = None):
    eng, prov = new_engine(seed, risk)
    asyncio.run(run_until(eng, prov, lambda e: bool(e.signals)))
    return eng, prov


def snapshot_for(eng: Engine, und: str) -> Snapshot:
    st = eng.u[und]
    now = eng.provider.now()
    chain = eng._chain_cache[und][1] if und in eng._chain_cache else None
    return Snapshot(
        underlying=und, now=now, candles_1m=st.builder.closed_list(), spot=st.last_ltp, last_tick_ts=st.last_tick_ts,
        health=eng.provider.get_health(), phase=eng.phase(now), chain=chain,
        session_open=asyncio.run(eng._session_open_async(now.date())))


@pytest.fixture(scope="session")
def put_scenario():
    eng, prov = first_signal_engine(PUT_SEED)
    sig = next(iter(eng.signals.values()))
    return eng, prov, sig


def clean_gates(eng: Engine, und: str):
    """Risk gates on a fresh RiskState (the scenario engine already holds an open paper position)."""
    from stratagy.risk import RiskState, risk_gate

    return risk_gate(eng.provider.now(), RiskState(), eng.risk, eng._cutoff_dt(eng.provider.now()))


def evaluate_with(eng: Engine, und: str, snap: Snapshot | None = None, risk: RiskSettings | None = None,
                  dh: DataHealthParams | None = None, gates=None):
    from stratagy.strategy import evaluate

    snap = snap or snapshot_for(eng, und)
    return evaluate(snap, eng.p, eng.cp, eng.cost, risk or eng.risk, dh or eng.dh,
                    gates if gates is not None else clean_gates(eng, und), ExchangeCalendar())
