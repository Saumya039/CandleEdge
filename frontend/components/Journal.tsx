"use client";
import { Fragment, useState } from "react";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import type { PaperTrade, Signal } from "@/lib/types";
import { istTime, num, rupees } from "@/lib/format";
import { DirTag, Panel, SimTag, StateTag, pnlClass } from "./ui";

function SignalDetail({ s }: { s: Signal }) {
  return (
    <div className="grid gap-3 p-3 md:grid-cols-2" data-testid="signal-detail">
      <div>
        <div className="mb-1 text-[11px] uppercase text-muted">Rationale</div>
        <ul className="list-disc pl-4">{s.rationale.map((r, i) => <li key={i}>{r}</li>)}</ul>
        <div className="mb-1 mt-2 text-[11px] uppercase text-muted">Transitions</div>
        <ol className="space-y-0.5">{s.transitions.map((t, i) => <li key={i}><span className="num text-muted">{istTime(t.ts)}</span> <StateTag state={t.to_state} /> {t.reason}</li>)}</ol>
      </div>
      <div>
        <div className="mb-1 text-[11px] uppercase text-muted">Indicator snapshot at signal time</div>
        <pre className="num overflow-x-auto rounded bg-bg p-2 text-[11px]">{JSON.stringify(s.indicators, null, 1)}</pre>
        <div className="mb-1 mt-2 text-[11px] uppercase text-muted">Gates at signal time</div>
        <ul className="text-[11px] text-muted">{s.checks.map((c) => <li key={c.name}>{c.passed ? "✓" : "✗"} {c.name}: {c.detail}</li>)}</ul>
      </div>
    </div>
  );
}

export function Journal({ onSelect }: { onSelect: (id: string, und: string) => void }) {
  const sigs = usePoll(api.signals, 3000);
  const trades = usePoll(api.trades, 3000);
  const [open, setOpen] = useState<string | null>(null);
  const tr: PaperTrade[] = trades.data ?? [];
  const sg: Signal[] = sigs.data ?? [];
  const byId = new Map(sg.map((s) => [s.id, s]));
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title="Signal ledger" right={<span className="text-muted">{sg.length} generated</span>}>
        <div className="overflow-x-auto">
          <table className="t" data-testid="signal-ledger">
            <thead><tr><th>Time</th><th>Underlying</th><th>Signal</th><th>State</th><th>Score</th><th>R:R</th><th>Strategy</th></tr></thead>
            <tbody>
              {sg.map((s) => (
                <Fragment key={s.id}>
                  <tr className="cursor-pointer hover:bg-panel2" onClick={() => setOpen(open === s.id ? null : s.id)} data-testid={`ledger-${s.id}`}>
                    <td className="num">{istTime(s.created_ts)}</td><td>{s.underlying}</td><td><DirTag dir={s.direction} /></td><td><StateTag state={s.state} /></td>
                    <td className="num">{s.score?.toFixed(1) ?? "n/a"}</td><td className="num">{s.plan.rr_t1.toFixed(2)}</td><td className="num">{s.strategy_version}</td>
                  </tr>
                  {open === s.id && (
                    <tr key={`${s.id}-d`}><td colSpan={7} className="!text-left"><SignalDetail s={s} /><button className="btn m-3" onClick={() => onSelect(s.id, s.underlying)}>Show on chart</button></td></tr>
                  )}
                </Fragment>
              ))}
              {sg.length === 0 && <tr><td colSpan={7} className="py-3 text-center text-muted">No setups generated yet this session. NO TRADE is a valid and common state.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Paper-trade journal" right={<span className="tag text-amber border-amber/60">PAPER · simulated fills</span>}>
        <div className="overflow-x-auto">
          <table className="t" data-testid="trade-journal">
            <thead><tr><th>Entry</th><th>Contract</th><th>Lots</th><th>Entry fill</th><th>Exit</th><th>Gross</th><th>Est. costs</th><th>Net</th><th>MFE/MAE</th><th>Exit reason</th></tr></thead>
            <tbody>
              {tr.map((t) => {
                const sells = t.fills.filter((f) => f.side === "SELL");
                const sig = byId.get(t.signal_id);
                return (
                  <tr key={t.id} data-testid={`trade-${t.id}`}>
                    <td className="num">{istTime(t.entry_ts)}</td>
                    <td className="num">{t.symbol} {sig?.plan.quote.status === "SIMULATED" && <SimTag label="SIM" />}</td>
                    <td className="num">{t.lots}{t.lots_open !== t.lots && ` (${t.lots_open} open)`}</td>
                    <td className="num">{num(t.entry_fill)}</td>
                    <td className="num">{sells.length ? sells.map((f) => num(f.price)).join(" / ") : t.status === "OPEN" ? <span className="text-amber">OPEN {t.mark !== null ? `mark ${num(t.mark)}` : ""}</span> : "—"}</td>
                    <td className={`num ${pnlClass(t.gross_pnl)}`}>{rupees(t.gross_pnl)}</td>
                    <td className="num text-muted">{rupees(t.est_costs)}</td>
                    <td className={`num font-semibold ${pnlClass(t.net_pnl)}`}>{rupees(t.net_pnl)}</td>
                    <td className="num text-muted">{rupees(t.mfe)} / {rupees(t.mae)}</td>
                    <td className="!text-left text-muted">{t.exit_reason || "—"}</td>
                  </tr>
                );
              })}
              {tr.length === 0 && <tr><td colSpan={10} className="py-3 text-center text-muted">No paper trades yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="px-3 py-2 text-[11px] text-muted">Fills are simulated at ask + slippage (buys) and bid − slippage (sells). Costs are configurable estimates, not exact charges. No broker order was sent for any row.</p>
      </Panel>
    </div>
  );
}
