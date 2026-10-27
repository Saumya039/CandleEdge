"use client";
import type { WatchRow } from "@/lib/types";
import { num, pct } from "@/lib/format";
import { Panel, Unavailable, pnlClass } from "./ui";

const SIGNAL_TAG: Record<string, string> = {
  CANDIDATE: "text-blue border-blue/50", TRIGGERED: "text-amber border-amber/60", TARGET_1: "text-up border-up/60",
  TARGET_2: "text-up border-up/60", STOPPED: "text-down border-down/60",
};

/** Compact quote board: Symbol, Last, Chg, Chg%. A signal tag only appears while a setup exists for that name. */
export function Watchlist({ rows, selected, onSelect }: { rows: WatchRow[]; selected: string; onSelect: (s: string) => void }) {
  return (
    <Panel title={`Watchlist (${rows.length})`}>
      <div className="grid grid-cols-[1fr_88px_72px_68px] gap-x-2 border-b border-line px-3 py-1 text-[11px] text-muted" aria-hidden>
        <span>Symbol</span><span className="text-right">Last</span><span className="text-right">Chg</span><span className="text-right">Chg%</span>
      </div>
      <ul data-testid="watchlist" className="max-h-[44vh] divide-y divide-[#18202a] overflow-y-auto">
        {rows.map((r) => {
          const chg = r.ltp !== null && r.prev_close !== null ? r.ltp - r.prev_close : null;
          const tone = pnlClass(r.change_pct);
          return (
            <li key={r.symbol} data-testid={`wl-${r.symbol}`} data-selected={r.symbol === selected}>
              <button onClick={() => onSelect(r.symbol)} aria-label={`${r.symbol} ${r.ltp ?? "no price"}`}
                className={`grid w-full grid-cols-[1fr_88px_72px_68px] items-center gap-x-2 px-3 py-[7px] text-left ${r.symbol === selected ? "bg-blue/15 ring-1 ring-inset ring-blue/60" : "hover:bg-panel2"}`}>
                <span className="flex min-w-0 items-center gap-1.5">
                  <b className="truncate text-[13px]">{r.symbol}</b>
                  {SIGNAL_TAG[r.signal_state] && <span className={`tag !px-1.5 !py-0 text-[10px] ${SIGNAL_TAG[r.signal_state]}`}>{r.signal_state === "CANDIDATE" ? "SETUP" : r.signal_state.replace("_", " ")}</span>}
                </span>
                <span className="num text-right text-[13px]">{r.ltp === null ? <Unavailable /> : num(r.ltp)}</span>
                <span className={`num text-right text-[12px] ${tone}`}>{chg === null ? "–" : (chg > 0 ? "+" : "") + num(chg)}</span>
                <span className={`num text-right text-[12px] ${tone}`}>{r.change_pct === null ? <Unavailable /> : pct(r.change_pct)}</span>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && <li className="py-3 text-center text-muted">No underlyings loaded (provider not started).</li>}
      </ul>
    </Panel>
  );
}
