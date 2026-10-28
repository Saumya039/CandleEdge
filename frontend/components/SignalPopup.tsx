"use client";
import { useEffect, useMemo, useState } from "react";
import type { PaperTrade, Signal, SignalState } from "@/lib/types";
import { istTime, num, rupees } from "@/lib/format";

interface Msg { key: string; signal: Signal; trade: PaperTrade | null }

type Tone = "buy" | "watch" | "profit" | "loss" | "neutral";
interface Copy { eyebrow: string; headline: (s: Signal) => string; action: (s: Signal) => string; tone: Tone }

const OPT = (s: Signal) => `${s.plan.contract.symbol}`;
const COPY: Partial<Record<SignalState, Copy>> = {
  CANDIDATE: {
    eyebrow: "SETUP FORMING · NOT YET A BUY", tone: "watch",
    headline: (s) => `GET READY: ${s.direction === "BUY_CALL" ? "BUY CALL" : "BUY PUT"} ${s.underlying}`,
    action: (s) => `Buy ${OPT(s)} only if ${s.underlying} trades inside ${num(s.plan.entry_zone_underlying[0])} – ${num(s.plan.entry_zone_underlying[1])}. If price runs past that zone without you, skip it. Do not chase.`,
  },
  TRIGGERED: {
    eyebrow: "ENTRY TRIGGERED", tone: "buy",
    headline: (s) => `BUY NOW: ${s.direction === "BUY_CALL" ? "CALL" : "PUT"} · ${s.plan.contract.option_type} ${num(s.plan.contract.strike, 0)}`,
    action: (s) => `Buy ${OPT(s)} at or below ${num(s.plan.premium_entry_limit)}. Exit if ${s.underlying} breaks ${num(s.plan.invalidation_underlying)} or the premium falls to ${num(s.plan.premium_stop)}.`,
  },
  TARGET_1: {
    eyebrow: "TARGET 1 REACHED", tone: "profit",
    headline: (s) => `SELL / BOOK PROFIT: ${OPT(s)}`,
    action: (s) => `Close at least part of ${OPT(s)} near ${num(s.plan.premium_target1)}. With 2 or more lots the plan moves the stop on the rest to breakeven. Next target: ${num(s.plan.premium_target2)}.`,
  },
  TARGET_2: {
    eyebrow: "TARGET 2 REACHED", tone: "profit",
    headline: (s) => `SELL ALL: ${OPT(s)}`,
    action: (s) => `Close the remaining position near ${num(s.plan.premium_target2)}. The plan is complete.`,
  },
  STOPPED: {
    eyebrow: "STOP HIT", tone: "loss",
    headline: (s) => `EXIT NOW: ${OPT(s)}`,
    action: () => "The stop level was reached. Close the position. A real stop may fill worse than the level.",
  },
  TIME_EXIT: {
    eyebrow: "TIME STOP", tone: "neutral",
    headline: (s) => `EXIT: ${OPT(s)}`,
    action: () => "The time limit for this setup passed without a target. Close the position.",
  },
  INVALIDATED: {
    eyebrow: "SETUP CANCELLED", tone: "neutral",
    headline: (s) => `DO NOT ENTER: ${s.underlying}`,
    action: (s) => `The reason for this setup no longer holds (underlying beyond ${num(s.plan.invalidation_underlying)} or conditions changed). If you already hold ${OPT(s)}, exit.`,
  },
};

const TONE: Record<Tone, string> = {
  buy: "border-up bg-[#0c2a1e]", watch: "border-amber bg-[#2a2310]", profit: "border-up bg-[#0c2a1e]", loss: "border-down bg-[#2f1216]", neutral: "border-line bg-panel",
};

/** Prominent, non-blocking alert for setup state changes. It tells you what the plan says to do and at which levels.
 * It never sends an order: paper trades are simulated and any real order is entirely your own manual decision. */
interface Track { sigs: Signal[] | null; seen: Set<string>; queue: Msg[] }
const keyOf = (s: Signal) => `${s.id}|${s.state}`;

/** Pure step: which signals reached a new alertable state since the last data. The first data after load only
 * records what already exists, so old setups do not pop up as if they were new. */
function advance(t: Track, signals: Signal[], trades: PaperTrade[]): Track {
  if (t.sigs === null) return { sigs: signals, seen: new Set(signals.map(keyOf)), queue: [] };
  // Forget signals that no longer exist (for example when a replay is rewound) so they can alert again.
  const ids = new Set(signals.map((x) => x.id));
  const seen = new Set([...t.seen].filter((k) => ids.has(k.split("|")[0])));
  const latest = new Map<string, Msg>();
  for (const s of signals) {
    const key = keyOf(s);
    if (seen.has(key)) continue;
    seen.add(key);
    // Only the latest state of each signal matters if several changed between polls.
    if (COPY[s.state]) latest.set(s.id, { key, signal: s, trade: trades.find((x) => x.signal_id === s.id) ?? null });
  }
  const queue = latest.size ? [...t.queue.filter((x) => !latest.has(x.signal.id)), ...latest.values()] : t.queue;
  return { sigs: signals, seen, queue };
}

/** Prominent, non-blocking alert for setup state changes. It tells you what the plan says to do and at which levels.
 * It never sends an order: paper trades are simulated and any real order is entirely your own manual decision. */
export function SignalPopup({ signals, trades, onShow }: { signals: Signal[]; trades: PaperTrade[]; onShow: (id: string, und: string) => void }) {
  const [track, setTrack] = useState<Track>({ sigs: null, seen: new Set(), queue: [] });
  if (track.sigs !== signals) setTrack(advance(track, signals, trades));
  const queue = track.queue;
  const msg = queue.length ? queue[queue.length - 1] : null;
  const dismiss = () => setTrack((t) => ({ ...t, queue: t.queue.slice(0, -1) }));
  useEffect(() => {
    if (!msg) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setTrack((t) => ({ ...t, queue: t.queue.slice(0, -1) })); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [msg]);

  const copy = useMemo(() => (msg ? COPY[msg.signal.state] ?? null : null), [msg]);
  if (!msg || !copy) return null;
  const s = msg.signal; const p = s.plan; const t = msg.trade;
  const sim = p.quote.status === "SIMULATED";
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-center p-3 sm:justify-end" role="presentation">
      <div role="alertdialog" aria-labelledby="signal-popup-title" aria-describedby="signal-popup-desc" data-testid="signal-popup" data-state={s.state}
        className={`pointer-events-auto w-[min(460px,100%)] rounded-md border-2 p-4 shadow-2xl ${TONE[copy.tone]}`}>
        <div className="flex items-start justify-between gap-3">
          <div className="text-[11px] font-semibold tracking-wider text-muted">{copy.eyebrow}{sim && <span className="ml-2 text-sim">SIMULATED</span>}</div>
          <button className="btn" onClick={dismiss} aria-label="Dismiss alert">Dismiss</button>
        </div>
        <h2 id="signal-popup-title" className="mt-1 text-[22px] font-bold leading-tight">{copy.headline(s)}</h2>
        <p className="num mt-0.5 text-muted">{p.contract.symbol} · exp {p.contract.expiry} · lot {p.lot_size} · {istTime(s.updated_ts)} IST</p>
        <p id="signal-popup-desc" className="mt-2 text-[14px]">{copy.action(s)}</p>
        <dl className="num mt-3 grid grid-cols-3 gap-x-3 gap-y-2 text-[12px]">
          <div><dt className="text-muted">Buy premium ≤</dt><dd className="text-[15px] font-semibold">{num(p.premium_entry_limit)}</dd></div>
          <div><dt className="text-muted">Stop (premium)</dt><dd className="text-[15px] font-semibold text-down">{num(p.premium_stop)}</dd></div>
          <div><dt className="text-muted">Invalidation ({s.underlying})</dt><dd className="text-[15px] font-semibold text-down">{num(p.invalidation_underlying)}</dd></div>
          <div><dt className="text-muted">Target 1 (premium)</dt><dd className="text-[15px] font-semibold text-up">{num(p.premium_target1)}</dd></div>
          <div><dt className="text-muted">Target 2 (premium)</dt><dd className="text-[15px] font-semibold text-up">{num(p.premium_target2)}</dd></div>
          <div><dt className="text-muted">Lots · reward:risk</dt><dd className="text-[15px] font-semibold">{p.lots} · {p.rr_t1.toFixed(1)}</dd></div>
        </dl>
        {t && t.status === "CLOSED" && (
          <p className="num mt-2 text-[12px]">Paper result: <b className={t.net_pnl >= 0 ? "text-up" : "text-down"}>{rupees(t.net_pnl)}</b> net of estimated costs · {t.exit_reason}</p>
        )}
        <p className="mt-3 text-[11px] text-muted">
          {sim ? "Simulated data. " : ""}Paper trade only: no order has been or will be sent by this app. Levels are model estimates, premium levels use an assumed delta, and a stop is not guaranteed to fill. Not investment advice.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <button className="btn btn-primary" onClick={() => { onShow(s.id, s.underlying); dismiss(); }}>Show on chart</button>
          {queue.length > 1 && <span className="text-[11px] text-muted">{queue.length - 1} more alert{queue.length > 2 ? "s" : ""}</span>}
        </div>
      </div>
    </div>
  );
}
