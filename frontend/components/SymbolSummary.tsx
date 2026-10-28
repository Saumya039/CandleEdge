"use client";
import type { WatchRow } from "@/lib/types";
import { istTime, num, pct } from "@/lib/format";
import { Panel, StateTag, Unavailable, pnlClass } from "./ui";

const REGIME: Record<string, string> = {
  TRENDING_UP: "Trending up", TRENDING_DOWN: "Trending down", RANGE_CHOP: "Range / chop", HIGH_VOLATILITY: "High volatility", INSUFFICIENT_DATA: "Not enough data",
};

/** Selected-name header: big last price, change, and the few facts that decide whether a setup is possible. */
export function SymbolSummary({ row, badge }: { row: WatchRow | undefined; badge: string }) {
  if (!row) return null;
  const chg = row.ltp !== null && row.prev_close !== null ? row.ltp - row.prev_close : null;
  const tone = pnlClass(row.change_pct);
  return (
    <Panel title={<span>{row.symbol}</span>} right={<StateTag state={row.signal_state} />}>
      <div className="px-3 pb-2 pt-3" data-testid="symbol-summary">
        <div className="flex items-baseline gap-3">
          <span className="num text-[30px] font-semibold leading-none">{row.ltp === null ? <Unavailable /> : num(row.ltp)}</span>
          <span className={`num text-[14px] ${tone}`}>{chg === null ? "" : (chg > 0 ? "+" : "") + num(chg)} {row.change_pct === null ? "" : pct(row.change_pct)}</span>
        </div>
        <div className="mt-1 text-[11px] text-muted">{badge} · last tick {istTime(row.last_tick_ts)} IST</div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
          <dt className="text-muted">Day open</dt><dd className="num text-right">{row.day_open === null ? <Unavailable /> : num(row.day_open)}</dd>
          <dt className="text-muted">Prev close</dt><dd className="num text-right">{row.prev_close === null ? <Unavailable /> : num(row.prev_close)}</dd>
          <dt className="text-muted">VWAP</dt>
          <dd className="num text-right">{row.vwap === null ? <Unavailable /> : <>{num(row.vwap)} <span className={row.vwap_relation === "ABOVE" ? "text-up" : "text-down"}>{row.vwap_relation?.toLowerCase()}</span></>}</dd>
          <dt className="text-muted">Trend</dt><dd className="text-right">{REGIME[row.regime] ?? row.regime}</dd>
          <dt className="text-muted">Volatility</dt><dd className="num text-right">{row.atr_pct === null ? <Unavailable /> : `${row.volatility.toLowerCase()} ${row.atr_pct.toFixed(2)}%`}</dd>
          <dt className="text-muted">Volume vs avg</dt><dd className="num text-right">{row.volume_ratio === null ? <Unavailable /> : `${row.volume_ratio.toFixed(2)}×`}</dd>
        </dl>
      </div>
    </Panel>
  );
}
