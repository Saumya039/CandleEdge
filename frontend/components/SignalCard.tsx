"use client";
import type { Evaluation, Signal } from "@/lib/types";
import { istTime, num, rupees } from "@/lib/format";
import { DirTag, Panel, SimTag, StateTag, Unavailable } from "./ui";

function Row({ k, children, testId }: { k: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[#18202a] py-1" data-testid={testId}>
      <span className="text-muted">{k}</span><span className="num text-right">{children}</span>
    </div>
  );
}

export function SignalCard({ signal }: { signal: Signal }) {
  const p = signal.plan;
  const sim = p.quote.status === "SIMULATED";
  return (
    <Panel title="Signal" right={<>{sim && <SimTag />}<StateTag state={signal.state} /></>}>
      <div className="space-y-2 p-3" data-testid="signal-card">
        <div className="flex flex-wrap items-center gap-2">
          <DirTag dir={signal.direction} />
          <b className="text-[14px]">{signal.underlying}</b>
          <span className="num text-muted">{p.contract.symbol}</span>
        </div>
        <div>
          <Row k="Contract">{p.contract.option_type} {num(p.contract.strike, 0)} · exp {p.contract.expiry}</Row>
          <Row k="Lot size (instrument master)">{p.lot_size}</Row>
          <Row k="Quote">{num(p.quote.bid)} / {num(p.quote.ask)} · spread {p.spread_pct.toFixed(2)}% · <span className={sim ? "text-sim" : "text-up"}>{p.quote.status}</span></Row>
          <Row k={`Entry zone (underlying)`} testId="entry-zone">{num(p.entry_zone_underlying[0])} – {num(p.entry_zone_underlying[1])}</Row>
          <Row k="Paper entry (ask + slippage)">{num(p.entry_premium_assumed)} <span className="text-muted">limit ≤ {num(p.premium_entry_limit)}</span></Row>
          <Row k="Invalidation (underlying)"><span className="text-down">{num(p.invalidation_underlying)}</span></Row>
          <Row k="Premium risk level (est.)"><span className="text-down">{num(p.premium_stop)}</span></Row>
          <Row k="Target 1 · underlying / premium est."><span className="text-up">{num(p.target1_underlying)} / {num(p.premium_target1)}</span></Row>
          <Row k="Target 2 · underlying / premium est."><span className="text-up">{num(p.target2_underlying)} / {num(p.premium_target2)}</span></Row>
          <Row k="Reward:risk to T1 / T2 (net)" testId="rr">{p.rr_t1.toFixed(2)} / {p.rr_t2.toFixed(2)}</Row>
          <Row k="Suggested lots · risk/lot">{p.lots} · {rupees(p.per_lot_risk)}</Row>
          <Row k="Est. round-trip costs / lot">{rupees(p.est_costs_round_trip_per_lot)} <span className="text-muted">(estimate)</span></Row>
          <Row k="Setup-quality score">{signal.score === null ? <Unavailable /> : `${signal.score.toFixed(1)} / 100`} <span className="text-muted">(not a probability)</span></Row>
          <Row k="Time stop">{istTime(p.time_stop)} IST</Row>
          <Row k="Strategy · timeframe">{signal.strategy_version} · {signal.trigger_tf}</Row>
          <Row k="Delta used">{p.delta_used.toFixed(2)} <span className="text-muted">({p.delta_source})</span></Row>
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Why it triggered</div>
          <ul className="list-disc space-y-0.5 pl-4" data-testid="rationale">{signal.rationale.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Invalidation &amp; method</div>
          <p className="text-muted">Underlying invalidation: {p.stop_method}. Targets: {p.target_method}. Premium levels are delta-based estimates and a stop is not guaranteed to fill at that price.</p>
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Score components</div>
          {signal.score_components.map((c) => (
            <div key={c.name} className="flex items-center gap-2 text-[11px]">
              <span className="w-32 text-muted">{c.name.replace(/_/g, " ")}</span>
              <span className="relative h-1.5 flex-1 rounded bg-line"><i className="absolute left-0 top-0 h-1.5 rounded bg-blue" style={{ width: `${c.fraction * 100}%` }} /></span>
              <span className="num w-20 text-right">{c.points.toFixed(1)}/{c.weight}</span>
              <span className="hidden w-48 truncate text-muted xl:inline" title={c.detail}>{c.detail}</span>
            </div>
          ))}
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Data used</div>
          <p className="text-muted">Sources: {signal.data_sources.join(", ")}. Signal time {istTime(signal.created_ts)} IST. Closed {signal.trigger_tf} candles + option-chain snapshot at that moment; ATR {num(signal.indicators.atr)}.</p>
        </div>
        {p.warnings.length > 0 && (
          <ul className="space-y-0.5 rounded border border-amber/40 bg-amber/5 p-2 text-[11px] text-amber">{p.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
        )}
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Lifecycle</div>
          <ol className="space-y-0.5 text-[11px]" data-testid="lifecycle">
            {signal.transitions.map((t, i) => (
              <li key={i}><span className="num text-muted">{istTime(t.ts)}</span> <StateTag state={t.to_state} /> {t.reason}</li>
            ))}
          </ol>
        </div>
      </div>
    </Panel>
  );
}

export function NoTradePanel({ ev, symbol }: { ev: Evaluation | null; symbol: string }) {
  const failed = ev?.checks.filter((c) => !c.passed) ?? [];
  return (
    <Panel title={`${symbol} · decision`} right={<span className="tag text-muted" data-testid="decision-tag">{ev?.decision === "CANDIDATE" ? "CANDIDATE" : "NO TRADE"}</span>}>
      <div className="space-y-2 p-3" data-testid="no-trade-panel">
        {!ev && <p className="text-muted">No evaluation yet. The engine evaluates on closed candles during the session.</p>}
        {ev && (
          <>
            <p className="text-[13px]"><b>NO TRADE</b> — a setup is only shown when every condition agrees. Regime: <b>{ev.regime.regime.replace(/_/g, " ")}</b>{ev.htf_regime && <> · {`HTF ${ev.htf_regime.replace(/_/g, " ").toLowerCase()}`}</>}.</p>
            <ul className="list-disc space-y-0.5 pl-4" data-testid="no-trade-reasons">
              {ev.reasons.length ? ev.reasons.map((r, i) => <li key={i}>{r}</li>) : <li>No reason recorded.</li>}
            </ul>
            <details>
              <summary className="cursor-pointer text-muted">Data-health &amp; risk gates ({ev.checks.length - failed.length}/{ev.checks.length} passing)</summary>
              <ul className="mt-1 space-y-0.5 text-[11px]">
                {ev.checks.map((c) => <li key={c.name} className={c.passed ? "text-muted" : "text-down"}>{c.passed ? "✓" : "✗"} {c.name.replace(/_/g, " ")}: {c.detail}</li>)}
              </ul>
            </details>
            <div className="grid grid-cols-2 gap-x-4 text-[11px] text-muted num">
              <span>ADX {ev.regime.adx === null ? "n/a" : ev.regime.adx.toFixed(1)}</span><span>RSI {ev.regime.rsi === null ? "n/a" : ev.regime.rsi.toFixed(1)}</span>
              <span>ATR {ev.regime.atr_pct === null ? "n/a" : `${ev.regime.atr_pct.toFixed(2)}%`}</span><span>Strategy {ev.strategy_version}</span>
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
