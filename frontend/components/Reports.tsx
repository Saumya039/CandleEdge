"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import type { Summary } from "@/lib/types";
import { rupees, num } from "@/lib/format";
import { Panel, SimTag, pnlClass } from "./ui";

function SummaryTable({ rows }: { rows: Record<string, Summary> }) {
  return (
    <table className="t">
      <thead><tr><th>Group</th><th>Trades</th><th>Win/Loss</th><th>Avg win</th><th>Avg loss</th><th>Expectancy</th><th>Net</th><th>Max DD</th></tr></thead>
      <tbody>
        {Object.entries(rows).map(([k, v]) => (
          <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{v.trades}</td><td className="num">{v.wins}/{v.losses}</td>
            <td className="num">{v.avg_win === null ? "n/a" : rupees(v.avg_win)}</td><td className="num">{v.avg_loss === null ? "n/a" : rupees(v.avg_loss)}</td>
            <td className={`num ${pnlClass(v.expectancy_per_trade)}`}>{v.expectancy_per_trade === null ? "n/a" : rupees(v.expectancy_per_trade)}</td>
            <td className={`num ${pnlClass(v.net_pnl)}`}>{rupees(v.net_pnl)}</td><td className="num">{rupees(v.max_drawdown)}</td></tr>
        ))}
        {Object.keys(rows).length === 0 && <tr><td colSpan={8} className="py-2 text-center text-muted">No closed trades in this group.</td></tr>}
      </tbody>
    </table>
  );
}

interface BacktestResult {
  origin: string; data_label: string; strategy_version: string; sessions: number; elapsed_s: number;
  overall: Summary; in_sample: Summary; out_of_sample: Summary; limitations: string[]; disclaimer: string; no_lookahead: string;
  per_session: { date: string; seed: number; net_pnl: number; trades: number; setups: number }[];
}

function Backtest() {
  const [sessions, setSessions] = useState(6);
  const [job, setJob] = useState<string | null>(null);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);
  const run = async () => {
    setRes(null); setErr(null);
    const { job: id } = await api.runBacktest(sessions, 100);
    setJob(id);
    timer.current = setInterval(async () => {
      const j = await api.backtestJob(id);
      if (j.status === "done") { setRes(j.result as unknown as BacktestResult); setJob(null); if (timer.current) clearInterval(timer.current); }
      if (j.status === "error") { setErr(j.error ?? "failed"); setJob(null); if (timer.current) clearInterval(timer.current); }
    }, 2500);
  };
  return (
    <Panel title="Backtest (replay through the same engine)" right={<span className="tag text-sim border-sim/60">BACKTEST · SIMULATED DATA</span>}>
      <div className="space-y-2 p-3">
        <p className="text-muted">Replays synthetic sessions with a virtual clock (no look-ahead), the current strategy and your risk settings. The underlying path and option chain are synthetic, so this validates the machinery, <b>not</b> real-market profitability. Real-history backtests need licensed historical option-chain data.</p>
        <div className="flex items-center gap-2">
          <label className="text-muted">Sessions <input className="input num w-16" type="number" min={2} max={30} value={sessions} onChange={(e) => setSessions(Number(e.target.value))} /></label>
          <button className="btn btn-primary" onClick={() => void run()} disabled={!!job} data-testid="backtest-run">{job ? "Running…" : "Run backtest"}</button>
          <span className="text-muted">≈ 8 s per session</span>
        </div>
        {err && <p className="text-down">{err}</p>}
        {res && (
          <div className="space-y-2" data-testid="backtest-result">
            <div className="flex flex-wrap gap-2"><span className="tag">{res.origin}</span><SimTag label={res.data_label} /><span className="tag">{res.strategy_version}</span></div>
            <SummaryTable rows={{ overall: res.overall, "in-sample (first half)": res.in_sample, "out-of-sample (second half)": res.out_of_sample }} />
            <p className="text-amber">{res.overall.sample_warning}</p>
            <ul className="list-disc pl-4 text-[11px] text-muted">{res.limitations.map((l) => <li key={l}>{l}</li>)}<li>{res.no_lookahead}</li></ul>
            <p className="text-[11px] text-muted">{res.disclaimer}</p>
          </div>
        )}
      </div>
    </Panel>
  );
}

export function Reports() {
  const rep = usePoll(api.sessionReport, 4000);
  const hist = usePoll(api.history, 8000);
  const r = rep.data;
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title={`Session report ${r ? `· ${r.date}` : ""}`} right={r ? <><span className="tag">{r.origin}</span>{r.data_label === "SIMULATED" ? <SimTag /> : <span className="tag text-up border-up/60">{r.data_label}</span>}</> : null}>
        <div className="space-y-3 p-3" data-testid="session-report">
          {!r && <p className="text-muted">No report yet.</p>}
          {r && (
            <>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-4">
                {([
                  ["Setups generated", r.summary.setups_generated], ["Taken (paper)", r.summary.setups_taken], ["Skipped", r.summary.setups_skipped],
                  ["Closed trades", r.summary.trades], ["Wins / losses", `${r.summary.wins} / ${r.summary.losses}`],
                  ["Expectancy / trade", r.summary.expectancy_per_trade === null ? "n/a" : rupees(r.summary.expectancy_per_trade)],
                  ["Gross P&L", rupees(r.summary.gross_pnl)], ["Est. costs", rupees(r.summary.est_costs)], ["Net P&L", rupees(r.summary.net_pnl)],
                  ["Max drawdown", rupees(r.summary.max_drawdown)], ["Open", r.summary.open_trades],
                ] as [string, string | number | undefined][]).map(([k, v]) => (
                  <div key={k}><div className="text-[11px] text-muted">{k}</div><div className="num text-[14px]">{v ?? "n/a"}</div></div>
                ))}
              </div>
              <p className="text-amber">{r.summary.sample_warning}</p>
              <div><div className="mb-1 text-[11px] uppercase text-muted">By underlying</div><SummaryTable rows={r.by_underlying} /></div>
              <div><div className="mb-1 text-[11px] uppercase text-muted">By direction</div><SummaryTable rows={r.by_direction} /></div>
              <div><div className="mb-1 text-[11px] uppercase text-muted">By timeframe</div><SummaryTable rows={r.by_timeframe} /></div>
              <div><div className="mb-1 text-[11px] uppercase text-muted">By strategy version</div><SummaryTable rows={r.by_strategy_version} /></div>
              <div><div className="mb-1 text-[11px] uppercase text-muted">By trend regime</div><SummaryTable rows={r.by_regime} /></div>
              <div><div className="mb-1 text-[11px] uppercase text-muted">Data-quality incidents</div>
                {r.data_quality_incidents.length ? <ul className="text-[11px] text-muted">{r.data_quality_incidents.map((h, i) => <li key={i}>{h.ts.slice(11, 19)} {h.kind}: {h.detail}</li>)}</ul> : <p className="text-muted">None recorded.</p>}</div>
              <div className="text-[11px] text-muted">Cost/slippage assumptions: brokerage ₹{num(r.cost_assumptions.brokerage_per_order, 0)}/order, STT {r.cost_assumptions.stt_sell_pct}% on sell, exchange {r.cost_assumptions.exchange_txn_pct}%, slippage max({r.cost_assumptions.slippage_ticks} ticks, {r.cost_assumptions.slippage_pct}%) per side — estimates only.</div>
              <p className="text-[11px] text-muted">{r.disclaimer}</p>
            </>
          )}
        </div>
      </Panel>
      <div className="space-y-3">
        <Panel title="History (paper journal, all stored sessions)" right={<span className="tag">PAPER</span>}>
          <div className="p-3">
            {hist.data ? <SummaryTable rows={{ overall: hist.data.overall, ...hist.data.days }} /> : <p className="text-muted">No history.</p>}
            {hist.data && hist.data.health_events.length > 0 && (
              <details className="mt-2"><summary className="cursor-pointer text-muted">Data-quality incidents ({hist.data.health_events.length})</summary>
                <ul className="text-[11px] text-muted">{hist.data.health_events.slice(0, 30).map((h, i) => <li key={i}>{h.ts.slice(0, 19)} {h.kind}: {h.detail}</li>)}</ul></details>
            )}
          </div>
        </Panel>
        <Backtest />
      </div>
    </div>
  );
}
