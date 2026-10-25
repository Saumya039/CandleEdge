"use client";
import type { ChainData, ChainSide } from "@/lib/types";
import { compact, num } from "@/lib/format";
import { Panel, SimTag, Unavailable } from "./ui";

const cell = (v: number | null, d = 2) => (v === null ? <Unavailable>—</Unavailable> : num(v, d));

function Side({ q, side }: { q: ChainSide | null; side: "ce" | "pe" }) {
  const bg = q?.selected ? "bg-amber/15" : q?.preferred ? "bg-blue/10" : "";
  if (!q) return <>{Array.from({ length: 7 }).map((_, i) => <td key={`${side}${i}`} className="text-muted">—</td>)}</>;
  const est = q.greeks_source === "estimated";
  const cols = [
    cell(q.ltp), cell(q.bid), cell(q.ask), q.spread_pct === null ? <Unavailable>—</Unavailable> : `${q.spread_pct.toFixed(1)}%`,
    q.volume === null ? <Unavailable>—</Unavailable> : compact(q.volume),
    <span key="oi">{q.oi === null ? <Unavailable>—</Unavailable> : compact(q.oi)}{q.oi_change !== null && <span className="text-muted"> ({q.oi_change > 0 ? "+" : ""}{compact(q.oi_change)})</span>}</span>,
    <span key="g">{q.iv === null ? <Unavailable>—</Unavailable> : `${(q.iv * 100).toFixed(1)}%`}{est && "*"} / {q.delta === null ? "—" : q.delta.toFixed(2)}{est && "*"}</span>,
  ];
  const ordered = side === "ce" ? cols : [...cols].reverse();
  return <>{ordered.map((c, i) => <td key={i} className={`num ${bg} ${q.age_s > 10 ? "text-muted line-through" : ""}`}>{c}</td>)}</>;
}

export function OptionChain({ data, error, symbol }: { data: ChainData | null; error: string | null; symbol: string }) {
  const head = ["LTP", "Bid", "Ask", "Spr", "Vol", "OI (Δ)", "IV / Δ"];
  return (
    <Panel
      title={`${symbol} option chain`}
      right={data?.available ? <><span className="text-muted">exp {data.expiry}</span><span className="num text-muted">fwd {num(data.forward)}</span>{data.status === "SIMULATED" ? <SimTag /> : <span className="tag text-up border-up/60">{data.status}</span>}</> : null}
    >
      {!data && <p className="p-3 text-muted">{error ? `Option chain unavailable: ${error}` : "Loading…"}</p>}
      {data && !data.available && <p className="p-3 text-muted" data-testid="chain-unavailable">Option chain unavailable: {data.reason ?? "provider did not return a chain"}. Nothing is estimated in its place.</p>}
      {data?.available && (
        <div className="overflow-x-auto">
          <table className="t" data-testid="chain-table">
            <thead>
              <tr><th colSpan={7} className="!text-center text-up">CALLS (CE)</th><th className="!text-center">Strike</th><th colSpan={7} className="!text-center text-down">PUTS (PE)</th></tr>
              <tr>{head.map((h) => <th key={`c${h}`}>{h}</th>)}<th className="!text-center">—</th>{[...head].reverse().map((h) => <th key={`p${h}`}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {data.rows.map((r) => {
                const atm = Math.abs(r.strike - data.forward) === Math.min(...data.rows.map((x) => Math.abs(x.strike - data.forward)));
                return (
                  <tr key={r.strike} className={atm ? "border-y border-blue/40" : ""}>
                    <Side q={r.ce} side="ce" />
                    <td className="num !text-center font-semibold">{num(r.strike, 0)}{atm && <span className="ml-1 text-blue">ATM</span>}</td>
                    <Side q={r.pe} side="pe" />
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data?.available && (
        <div className="space-y-0.5 px-3 py-2 text-[11px] text-muted">
          <div>* Estimated (Black-76) from the option price; provider Greeks are shown without an asterisk. Struck-through = quote older than 10 s. Highlighted: <span className="text-amber">selected by an active setup</span>, <span className="text-blue">preferred by filters</span>.</div>
          <div>PCR in this strike window: <b className="num text-ink">{data.pcr_in_window ?? "Unavailable"}</b>. {data.context_note}</div>
          <div>Lot size and tick size come from the instrument master: {data.rows.find((r) => r.ce)?.ce?.lot_size ?? "n/a"} / {data.rows.find((r) => r.ce)?.ce?.tick_size ?? "n/a"}.</div>
        </div>
      )}
    </Panel>
  );
}
