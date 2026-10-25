"""Session runner and backtest harness.

A backtest here replays a provider's data through the SAME engine used live (ticks -> closed candles ->
strategy -> signals -> paper fills), advancing a virtual clock, so no future candle, tick or option quote can
be seen: the provider only releases data up to `now`. Option prices come from the provider's chain at `now`.

IMPORTANT: with the built-in simulator the underlying path and the option chain are SYNTHETIC. Results show
that the machinery works; they say nothing about real-market profitability. A backtest on real history needs
licensed historical option-chain data, which this repository does not include (see README)."""

from __future__ import annotations

import time as _time
from datetime import date, time, timedelta
from typing import Any

from .config import ContractParams, CostModel, DataHealthParams, RiskSettings, StrategyParams
from .engine import Engine
from .journal import Journal
from .models import IST
from .providers.simulator import SimulatorProvider
from .reports import DISCLAIMER, session_report, summarize_trades


async def run_session(engine: Engine, provider: SimulatorProvider, step_s: float = 10.0,
                      until: time = time(15, 45)) -> None:
    await engine.start()
    end = provider.now().replace(hour=until.hour, minute=until.minute, second=0, microsecond=0)
    while provider.now() < end:
        provider.advance(step_s)
        await engine.process()
    await engine.stop()


async def run_backtest(
    seeds: list[int],
    start_date: date,
    risk: RiskSettings | None = None,
    params: StrategyParams | None = None,
    cost: CostModel | None = None,
    journal: Journal | None = None,
    split: float = 0.5,
) -> dict[str, Any]:
    """One synthetic session per seed on consecutive weekdays. Parameters are fixed up front (no fitting);
    sessions are split chronologically into an in-sample and an out-of-sample half and reported separately."""
    risk = (risk or RiskSettings()).model_copy(update={"confirmed": True})
    params = params or StrategyParams()
    cost = cost or CostModel()
    days: list[dict[str, Any]] = []
    d = start_date
    t0 = _time.time()
    for seed in seeds:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        prov = SimulatorProvider(seed=seed, sim_date=d)
        eng = Engine(prov, calendar=None, params=params, cost=cost, risk=risk, journal=journal, origin="BACKTEST",
                     health_params=DataHealthParams(), contract_params=ContractParams(), eval_interval_s=30.0)
        await run_session(eng, prov)
        rep = session_report(eng, d)
        days.append({"date": d.isoformat(), "seed": seed, "summary": rep["summary"], "trades": rep["trades"]})
        d += timedelta(days=1)
    cut = max(1, int(len(days) * split))
    all_trades = [t for x in days for t in x["trades"]]
    return {
        "origin": "BACKTEST",
        "data_label": "SIMULATED (synthetic underlying and option chain)",
        "strategy_version": params.version,
        "sessions": len(days),
        "elapsed_s": round(_time.time() - t0, 1),
        "overall": summarize_trades(all_trades),
        "in_sample": summarize_trades([t for x in days[:cut] for t in x["trades"]]),
        "out_of_sample": summarize_trades([t for x in days[cut:] for t in x["trades"]]),
        "per_session": [{"date": x["date"], "seed": x["seed"], "net_pnl": x["summary"]["net_pnl"],
                         "trades": x["summary"]["trades"], "setups": x["summary"]["setups_generated"]} for x in days],
        "cost_assumptions": cost.model_dump(),
        "no_lookahead": "Data is released by a virtual clock; indicators use closed candles only.",
        "limitations": [
            "Underlying prices, volume, option quotes, IV, OI are synthetic.",
            "Real historical option-chain/quote data is not bundled; an honest real-data backtest needs it.",
            "Fills use ask+slippage / bid-slippage and estimated costs; real fills differ.",
            "Parameters were not optimised on these sessions; in-sample/out-of-sample split is chronological.",
        ],
        "disclaimer": DISCLAIMER,
        "tz": str(IST),
    }
