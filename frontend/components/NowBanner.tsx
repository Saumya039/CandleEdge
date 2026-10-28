"use client";
import type { AppState } from "@/lib/types";
import { dirLabel, num } from "@/lib/format";

/** One plain sentence on what the person should do right now. It only restates the app's own state. */
export function nowMessage(s: AppState): { tone: "info" | "warn" | "bad" | "ok"; text: string } {
  if (s.stale) return { tone: "bad", text: "The data feed has a problem. Do not act on any signal until it recovers." };
  if (s.risk_state.paused) return { tone: "warn", text: "New entries are paused. No new setups will be shown." };
  if (!s.risk_settings.confirmed) return { tone: "warn", text: "Before the app can size a trade, open Risk & settings and confirm your limits." };
  if (s.badge === "MARKET CLOSED" || s.phase === "POST_CLOSE") return { tone: "info", text: "The market is closed. Review today in the Journal and Reports tabs." };
  if (s.badge === "PRE-MARKET") return { tone: "info", text: "Market not open yet. The app is getting ready and will start scanning after the opening range forms." };
  const open = s.active_signals.find((x) => x.state === "TRIGGERED");
  if (open) return { tone: "ok", text: `Open setup: ${dirLabel(open.direction)} ${open.plan.contract.symbol}. Buy at or below ${num(open.plan.premium_entry_limit)}, stop ${num(open.plan.premium_stop)}, first target ${num(open.plan.premium_target1)}. Paper trade only.` };
  const cand = s.active_signals.find((x) => x.state === "CANDIDATE");
  if (cand) return { tone: "info", text: `Setup forming: ${dirLabel(cand.direction)} ${cand.underlying}. Wait for price to enter ${num(cand.plan.entry_zone_underlying[0])} to ${num(cand.plan.entry_zone_underlying[1])}. Don't chase it.` };
  return { tone: "info", text: "Nothing to do right now. No clear setup, and that is normal. The app will pop up an alert when one appears." };
}

/** Counts the first NO TRADE reason of every watched name (numbers masked) so a quiet screen explains itself. */
export function blockerSummary(rows: AppState["watchlist"], top = 5): { reason: string; count: number }[] {
  const m = new Map<string, number>();
  for (const r of rows) {
    if (r.decision === "CANDIDATE" || !r.no_trade_reasons.length) continue;
    const k = r.no_trade_reasons[0].replace(/-?\d+(\.\d+)?/g, "#").slice(0, 110);
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count).slice(0, top);
}

const TONE = { info: "border-line", warn: "border-amber", bad: "border-down", ok: "border-up" } as const;

export function NowBanner({ s }: { s: AppState }) {
  const m = nowMessage(s);
  const why = s.active_signals.length === 0 ? blockerSummary(s.watchlist) : [];
  return (
    <section className={`panel border-l-4 px-3 py-2 text-[14px] ${TONE[m.tone]}`} data-testid="now-banner" aria-live="polite">
      <div className="flex items-center gap-3">
        <b className="whitespace-nowrap text-[11px] uppercase tracking-wider text-muted">What to do now</b>
        <span>{m.text}</span>
      </div>
      {why.length > 0 && (
        <details className="mt-1 text-[12px] text-muted" data-testid="blockers">
          <summary className="cursor-pointer">Why no setup right now ({s.watchlist.length} names checked)</summary>
          <ul className="mt-1 list-disc pl-5">
            {why.map((w) => <li key={w.reason}><b className="num text-ink">{w.count}</b> × {w.reason}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}
