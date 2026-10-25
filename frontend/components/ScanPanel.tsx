"use client";
import { useMemo, useState } from "react";
import type { AppState, Signal } from "@/lib/types";
import { istTime, num } from "@/lib/format";
import { DirTag, Panel, StateTag } from "./ui";

const INDEX_SYMBOLS = new Set(["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]);

export function ScanPanel({ state, signals, onSelect }: { state: AppState; signals: Signal[]; onSelect: (id: string, und: string) => void }) {
  const [und, setUnd] = useState("ALL");
  const [kind, setKind] = useState("ALL");
  const [tf, setTf] = useState("ALL");
  const [type, setType] = useState("ALL");
  const [maxSpread, setMaxSpread] = useState("");
  const [minRR, setMinRR] = useState("");
  const [expiry, setExpiry] = useState("ALL");

  const expiries = useMemo(() => Array.from(new Set(signals.map((s) => s.plan.contract.expiry))), [signals]);
  const rows = useMemo(() => {
    const ranked = signals
      .filter((s) => (und === "ALL" || s.underlying === und) && (kind === "ALL" || (kind === "INDEX") === INDEX_SYMBOLS.has(s.underlying)))
      .filter((s) => tf === "ALL" || s.trigger_tf === tf)
      .filter((s) => type === "ALL" || s.direction === type)
      .filter((s) => maxSpread === "" || s.plan.spread_pct <= Number(maxSpread))
      .filter((s) => minRR === "" || s.plan.rr_t1 >= Number(minRR))
      .filter((s) => expiry === "ALL" || s.plan.contract.expiry === expiry);
    return ranked.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }, [signals, und, kind, tf, type, maxSpread, minRR, expiry]);

  const showNoTrade = type === "ALL" || type === "NO_TRADE";
  const noTrade = state.watchlist.filter(
    (w) => w.decision !== "CANDIDATE" && (und === "ALL" || w.symbol === und) && (kind === "ALL" || (kind === "INDEX") === INDEX_SYMBOLS.has(w.symbol)),
  );
  const sel = "input w-auto";
  return (
    <Panel title="Scan · ranked by transparent setup-quality score" right={<span className="text-muted">strategy {state.strategy.version}</span>}>
      <div className="flex flex-wrap items-end gap-2 border-b border-line p-3" role="search" aria-label="Scan filters">
        <label className="text-muted">Underlying<select className={sel} value={und} onChange={(e) => setUnd(e.target.value)}><option>ALL</option>{state.watchlist.map((w) => <option key={w.symbol}>{w.symbol}</option>)}</select></label>
        <label className="text-muted">Type<select className={sel} value={kind} onChange={(e) => setKind(e.target.value)}><option value="ALL">All</option><option value="INDEX">Index</option><option value="STOCK">Stock</option></select></label>
        <label className="text-muted">Timeframe<select className={sel} value={tf} onChange={(e) => setTf(e.target.value)}><option>ALL</option><option>3m</option><option>5m</option><option>15m</option></select></label>
        <label className="text-muted">Signal<select className={sel} value={type} onChange={(e) => setType(e.target.value)} data-testid="scan-type"><option value="ALL">All</option><option value="BUY_CALL">BUY CALL</option><option value="BUY_PUT">BUY PUT</option><option value="NO_TRADE">NO TRADE</option></select></label>
        <label className="text-muted">Max spread %<input className="input w-20" inputMode="decimal" value={maxSpread} onChange={(e) => setMaxSpread(e.target.value)} placeholder="any" /></label>
        <label className="text-muted">Min R:R<input className="input w-20" inputMode="decimal" value={minRR} onChange={(e) => setMinRR(e.target.value)} placeholder="any" /></label>
        <label className="text-muted">Expiry<select className={sel} value={expiry} onChange={(e) => setExpiry(e.target.value)}><option>ALL</option>{expiries.map((e) => <option key={e}>{e}</option>)}</select></label>
      </div>
      <div className="overflow-x-auto">
        <table className="t" data-testid="scan-table">
          <thead><tr><th>Time</th><th>Underlying</th><th>Signal</th><th>Contract</th><th>Score</th><th>R:R (T1)</th><th>Spread</th><th>State</th></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className="cursor-pointer hover:bg-panel2" onClick={() => onSelect(s.id, s.underlying)} data-testid={`scan-${s.id}`}>
                <td className="num">{istTime(s.created_ts)}</td><td>{s.underlying}</td><td><DirTag dir={s.direction} /></td>
                <td className="num">{s.plan.contract.symbol}</td><td className="num">{s.score === null ? "n/a" : s.score.toFixed(1)}</td>
                <td className="num">{s.plan.rr_t1.toFixed(2)}</td><td className="num">{s.plan.spread_pct.toFixed(2)}%</td><td><StateTag state={s.state} /></td>
              </tr>
            ))}
            {showNoTrade && noTrade.map((w) => (
              <tr key={`nt-${w.symbol}`} className="text-muted" data-testid={`scan-nt-${w.symbol}`}>
                <td className="num">{istTime(state.now)}</td><td>{w.symbol}</td><td><span className="tag">NO TRADE</span></td>
                <td colSpan={5} className="!text-left">{w.no_trade_reasons[0] ?? "No setup"}</td>
              </tr>
            ))}
            {rows.length === 0 && (!showNoTrade || noTrade.length === 0) && <tr><td colSpan={8} className="py-3 text-center text-muted">Nothing matches the filters.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="px-3 py-1.5 text-[11px] text-muted">The score ranks setups by component; it is not a probability of profit. Min liquidity is enforced by the contract filters ({num(state.risk_settings.min_reward_risk)}× minimum R:R from your risk settings).</div>
    </Panel>
  );
}
