"use client";
import type { WatchRow } from "@/lib/types";
import { compact, num, pct } from "@/lib/format";
import { Panel, StateTag, Unavailable, pnlClass } from "./ui";

const REGIME: Record<string, string> = {
  TRENDING_UP: "text-up", TRENDING_DOWN: "text-down", RANGE_CHOP: "text-muted", HIGH_VOLATILITY: "text-amber", INSUFFICIENT_DATA: "text-muted",
};
const REGIME_SHORT: Record<string, string> = {
  TRENDING_UP: "trend ↑", TRENDING_DOWN: "trend ↓", RANGE_CHOP: "range/chop", HIGH_VOLATILITY: "high vol", INSUFFICIENT_DATA: "no data",
};

export function Watchlist({ rows, selected, onSelect }: { rows: WatchRow[]; selected: string; onSelect: (s: string) => void }) {
  return (
    <Panel title="Watchlist">
      <ul data-testid="watchlist" className="max-h-[70vh] divide-y divide-[#18202a] overflow-y-auto">
        {rows.map((r) => (
          <li key={r.symbol} data-testid={`wl-${r.symbol}`} data-selected={r.symbol === selected}>
            <button onClick={() => onSelect(r.symbol)} className={`grid w-full grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 px-3 py-2 text-left ${r.symbol === selected ? "bg-blue/10" : "hover:bg-panel2"}`}>
              <span className="flex items-baseline gap-2">
                <b className="text-[13px]">{r.symbol}</b>
                <span className={`text-[11px] ${REGIME[r.regime] ?? ""}`}>{REGIME_SHORT[r.regime] ?? r.regime}</span>
              </span>
              <span className="num text-right text-[14px]">{r.ltp === null ? <Unavailable /> : num(r.ltp)}</span>
              <span className="text-[11px] text-muted">
                VWAP {r.vwap_relation === null ? <Unavailable /> : <span className={r.vwap_relation === "ABOVE" ? "text-up" : "text-down"}>{r.vwap_relation.toLowerCase()}</span>}
                {" · "}vol {r.volume_ratio === null ? <Unavailable /> : <span className="num">{r.volume_ratio.toFixed(2)}×</span>}
                {" · "}{r.atr_pct === null ? "volatility n/a" : <span className={r.volatility === "HIGH" ? "text-amber" : ""}>{r.volatility.toLowerCase()} {r.atr_pct.toFixed(2)}%</span>}
              </span>
              <span className="flex items-center justify-end gap-2">
                <span className={`num text-[11px] ${pnlClass(r.change_pct)}`}>{r.change_pct === null ? <Unavailable /> : pct(r.change_pct)}</span>
                <StateTag state={r.signal_state} />
              </span>
            </button>
          </li>
        ))}
        {rows.length === 0 && <li className="py-3 text-center text-muted">No underlyings loaded (provider not started).</li>}
      </ul>
      {rows.length > 0 && <div className="px-3 py-1.5 text-[11px] text-muted">Volume = last closed bar vs 20-bar average. Ticks dropped (out-of-order / duplicate): {compact(rows.reduce((a, r) => a + r.dropped_out_of_order + r.dropped_duplicates, 0))}</div>}
    </Panel>
  );
}
