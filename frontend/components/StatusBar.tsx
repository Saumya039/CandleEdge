"use client";
import type { AppState } from "@/lib/types";
import { countdown, istTime } from "@/lib/format";
import { Banner } from "./ui";

const BADGE: Record<string, string> = {
  LIVE: "bg-up/20 text-up border-up/60", OPEN: "bg-up/10 text-up border-up/50", "PRE-MARKET": "bg-blue/15 text-blue border-blue/50",
  "MARKET CLOSED": "bg-line text-muted border-line", "STALE DATA": "bg-down/20 text-down border-down/70 animate-pulse",
  SIMULATION: "bg-sim/15 text-sim border-sim/60",
};

export function StatusBar({ s, error, onPause }: { s: AppState | null; error: string | null; onPause: (p: boolean) => void }) {
  if (!s) {
    return (
      <header className="panel flex items-center gap-3 px-3 py-2" data-testid="status-bar">
        <span className="font-semibold">Stratagy</span>
        <span className="tag text-muted">{error ? "NO DATA" : "CONNECTING…"}</span>
      </header>
    );
  }
  const d = s.data;
  const age = s.watchlist.map((w) => w.tick_age_s).filter((x): x is number => x !== null);
  const worst = age.length ? Math.min(...age) : null; // freshest name = feed age; one illiquid name must not look like a dead feed
  return (
    <header className="flex flex-col gap-2" data-testid="status-bar">
      <div className="panel flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
        <span className="text-[15px] font-semibold tracking-tight">Stratagy <span className="text-muted font-normal">· NSE F&amp;O options-buying workstation</span></span>
        <span data-testid="session-badge" className={`tag border ${BADGE[s.badge] ?? ""}`}>{s.badge}</span>
        <span className="text-muted">Phase <b className="text-ink">{s.phase.replace(/_/g, " ")}</b></span>
        <span className="text-muted">{d.is_simulated ? "Sim clock" : "IST"} <b className="num text-ink" data-testid="ist-clock">{istTime(s.now)}</b> <span className="text-muted">IST</span></span>
        {s.next_event && <span className="text-muted">{s.next_event.label} in <b className="num text-ink">{countdown(s.next_event.seconds)}</b></span>}
        <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-muted">Provider <b className="text-ink">{d.provider}</b> <span className={d.status === "LIVE" ? "text-up" : d.status === "SIMULATED" ? "text-sim" : "text-down"}>{d.status}</span></span>
          <span className="text-muted">Feed <b className={d.connected ? "text-up" : "text-down"}>{d.connected ? "connected" : "DISCONNECTED"}</b> <span className="text-muted">({d.transport})</span></span>
          <span className="text-muted">Last tick <b className="num text-ink">{istTime(d.last_tick_ts)}</b>{worst !== null && <span className={`num ml-1 ${worst > 15 ? "text-down" : "text-muted"}`}>({worst.toFixed(0)}s ago)</span>}</span>
          <span className="text-muted">Latency <b className="num text-ink">{d.latency_ms === null ? "n/a" : `${d.latency_ms.toFixed(0)} ms`}</b></span>
          <button className={`btn ${s.risk_state.paused ? "btn-primary" : "btn-danger"}`} data-testid="pause-btn" onClick={() => onPause(!s.risk_state.paused)}
            title="Global pause: stops NEW paper entries. Never touches broker positions.">
            {s.risk_state.paused ? "▶ Resume signals" : "⏸ Pause new entries"}
          </button>
        </span>
      </div>
      {error && <Banner tone="bad" testId="api-error">Cannot reach the backend ({error}). Showing the last known data below; nothing here is updating.</Banner>}
      {d.is_simulated && (
        <Banner tone="sim" testId="sim-banner">
          SIMULATION — all prices, volume, option quotes and signals are synthetic and generated from a seeded model. This is NOT market data and no real
          order is ever placed.
        </Banner>
      )}
      {s.stale && <Banner tone="bad" testId="stale-banner">DATA STALE — underlying ticks are older than the limit. New signals are suppressed (fail closed) until the feed recovers.</Banner>}
      {!d.connected && !d.is_simulated && <Banner tone="bad">Provider disconnected: {d.message || "no connection"}.</Banner>}
      {d.start_error && (
        <Banner tone="warn" testId="provider-error">
          Live data is not active: {d.start_error}
          {d.missing_credentials.length > 0 && <> Missing: <b>{d.missing_credentials.join(", ")}</b>.</>} See the Provider tab for setup. Nothing is being faked.
        </Banner>
      )}
      {!s.calendar.verified && !d.is_simulated && <Banner tone="warn">{s.calendar.note || "Exchange calendar not configured: holidays unverified."}</Banner>}
      {s.risk_state.paused && <Banner tone="warn" testId="pause-banner">Trading PAUSED ({s.risk_state.pause_reason || "manual"}): no new paper entries. Existing paper positions are still managed.</Banner>}
      {s.risk_settings.defaults_in_use && <Banner tone="info" testId="risk-defaults">Paper trading on DEFAULT risk limits: Rs {s.risk_settings.max_risk_per_trade.toLocaleString("en-IN")} risk per trade, {s.risk_settings.max_open_positions} open position, {s.risk_settings.max_trades_per_session} trades, Rs {s.risk_settings.max_daily_loss.toLocaleString("en-IN")} daily loss limit. Change them in Risk &amp; settings.</Banner>}
      {!s.risk_settings.confirmed && <Banner tone="info" testId="risk-unconfirmed">Risk settings are not confirmed, so no setup can be sized or taken. Open Risk &amp; settings and confirm your limits.</Banner>}
    </header>
  );
}
