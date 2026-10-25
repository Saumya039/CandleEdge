"""Session / historical reporting. Backtest, paper and live-observation results are labelled separately."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

DISCLAIMER = (
    "Results are for research only. Paper and backtest P&L use assumed fills, slippage and cost estimates and are "
    "not a forecast of future results or a promise of returns."
)


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    closed.sort(key=lambda t: str(t.get("exit_ts") or t.get("entry_ts")))
    nets = [t["net_pnl"] for t in closed]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    n = len(nets)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / n, 1) if n else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "expectancy_per_trade": round(sum(nets) / n, 2) if n else None,
        "gross_pnl": round(sum(t["gross_pnl"] for t in closed), 2),
        "est_costs": round(sum(t["est_costs"] for t in closed), 2),
        "net_pnl": round(sum(nets), 2),
        "max_drawdown": round(max_dd, 2),
        "open_trades": len([t for t in trades if t.get("status") == "OPEN"]),
        "sample_warning": "Fewer than 30 trades: statistics are not meaningful" if n < 30 else "",
    }


def _group(trades: list[dict], key) -> dict[str, dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        g[str(key(t))].append(t)
    return {k: summarize_trades(v) for k, v in g.items()}


def session_report(engine, d: date) -> dict[str, Any]:
    sigs = [s for s in engine.signals.values() if s.created_ts.date() == d]
    trades = [t.model_dump(mode="json") for t in engine.trades.values() if t.entry_ts.date() == d]
    taken_ids = {t["signal_id"] for t in trades}
    sig_by_id = {s.id: s for s in sigs}
    skipped = [s for s in sigs if s.id not in taken_ids]
    by_state: dict[str, int] = defaultdict(int)
    for s in sigs:
        by_state[s.state.value] += 1
    regimes = {s.id: s.indicators for s in sigs}
    _ = regimes

    def regime_of(t: dict) -> str:
        s = sig_by_id.get(t["signal_id"])
        ev = engine.u[s.underlying].latest_eval if s else None
        return ev.regime.regime.value if ev else "n/a"

    return {
        "date": d.isoformat(),
        "origin": engine.origin,
        "data_label": "SIMULATED" if engine.provider.name in ("simulator", "replay") else "LIVE-OBSERVATION",
        "strategy_versions": sorted({s.strategy_version for s in sigs} | {engine.p.version}),
        "summary": {
            **summarize_trades(trades),
            "setups_generated": len(sigs),
            "setups_taken": len(taken_ids),
            "setups_skipped": len(skipped),
            "setups_by_final_state": dict(by_state),
        },
        "by_underlying": _group(trades, lambda t: t["underlying"]),
        "by_direction": _group(trades, lambda t: t["direction"]),
        "by_timeframe": _group(trades, lambda t: sig_by_id[t["signal_id"]].trigger_tf if t["signal_id"] in sig_by_id else "n/a"),
        "by_strategy_version": _group(trades, lambda t: sig_by_id[t["signal_id"]].strategy_version if t["signal_id"] in sig_by_id else "n/a"),
        "by_regime": _group(trades, regime_of),
        "cost_assumptions": engine.cost.model_dump(),
        "data_quality_incidents": [h for h in engine.health_log if h["ts"][:10] == d.isoformat()],
        "trades": trades,
        "disclaimer": DISCLAIMER,
    }
