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

const TONE = { info: "border-line", warn: "border-amber", bad: "border-down", ok: "border-up" } as const;

export function NowBanner({ s }: { s: AppState }) {
  const m = nowMessage(s);
  return (
    <section className={`panel flex items-center gap-3 border-l-4 px-3 py-2 text-[14px] ${TONE[m.tone]}`} data-testid="now-banner" aria-live="polite">
      <b className="whitespace-nowrap text-[11px] uppercase tracking-wider text-muted">What to do now</b>
      <span>{m.text}</span>
    </section>
  );
}
