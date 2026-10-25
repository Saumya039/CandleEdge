"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AppState, RiskSettings } from "@/lib/types";
import { rupees } from "@/lib/format";
import { Panel, pnlClass } from "./ui";

type Form = Omit<RiskSettings, "paper_square_off" | "confirmed">;

function toForm(r: RiskSettings): Form {
  const { paper_square_off: _a, confirmed: _b, ...rest } = r;
  void _a; void _b;
  return { ...rest, trading_cutoff: r.trading_cutoff.slice(0, 5) };
}

export function RiskPanel({ s, onChanged }: { s: AppState; onChanged: () => void }) {
  const [f, setF] = useState<Form>(toForm(s.risk_settings));
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [seen, setSeen] = useState(s.risk_settings);
  if (seen !== s.risk_settings) {
    // adjust state during render: follow server values until the user starts editing
    setSeen(s.risk_settings);
    if (!dirty) setF(toForm(s.risk_settings));
  }

  const set = <K extends keyof Form>(k: K, v: Form[K]) => { setF((p) => ({ ...p, [k]: v })); setDirty(true); };
  const numField = (k: keyof Form, label: string, step = 1, hint?: string) => (
    <label className="block text-muted">{label}
      <input className="input num mt-0.5" type="number" min={0} step={step} value={f[k] as number} data-testid={`risk-${k}`}
        onChange={(e) => set(k, Number(e.target.value) as never)} />
      {hint && <span className="text-[10px]">{hint}</span>}
    </label>
  );
  const save = async () => {
    try {
      await api.setRisk({ ...f, confirmed: true });
      setDirty(false); setMsg("Risk settings confirmed and saved (audited)."); onChanged();
    } catch (e) { setMsg(e instanceof ApiError ? `Rejected: ${e.message}` : "Failed"); }
  };
  const rs = s.risk_state;
  return (
    <Panel title="Risk & paper trading" right={<span className={`tag ${s.risk_settings.confirmed ? "text-up border-up/60" : "text-amber border-amber/60"}`} data-testid="risk-confirmed-tag">{s.risk_settings.confirmed ? "CONFIRMED" : "NOT CONFIRMED"}</span>}>
      <div className="space-y-3 p-3">
        <div className="grid grid-cols-2 gap-2 text-[12px]" data-testid="risk-state">
          <div className="text-muted">Day P&amp;L (net, est.)</div><div className={`num text-right ${pnlClass(rs.realized_net + rs.unrealized)}`}>{rupees(rs.realized_net + rs.unrealized)}</div>
          <div className="text-muted">Trades / limit</div><div className="num text-right">{rs.trades_today} / {s.risk_settings.max_trades_per_session}</div>
          <div className="text-muted">Open positions / limit</div><div className="num text-right">{rs.open_positions} / {s.risk_settings.max_open_positions}</div>
          <div className="text-muted">Loss streak</div><div className="num text-right">{rs.consecutive_losses}{rs.cooldown_until && <span className="text-amber"> · cooldown</span>}</div>
        </div>
        <details open={!s.risk_settings.confirmed}>
          <summary className="cursor-pointer text-muted">Limits (all yours; nothing is silently overridden)</summary>
          <form className="mt-2 grid grid-cols-2 gap-2" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            {numField("capital", "Capital (₹)", 10000)}
            {numField("max_risk_per_trade", "Max risk / trade (₹)", 500)}
            {numField("max_daily_loss", "Max daily loss (₹)", 500)}
            {numField("max_premium_deployed", "Max premium deployed (₹)", 5000)}
            {numField("max_open_positions", "Max open positions")}
            {numField("max_trades_per_session", "Max trades / session")}
            {numField("cooldown_after_losses", "Cooldown after N losses")}
            {numField("cooldown_minutes", "Cooldown (min)")}
            {numField("min_reward_risk", "Min reward:risk", 0.1, "net of spread, slippage and costs")}
            <label className="block text-muted">Entry cutoff (IST)
              <input className="input num mt-0.5" type="time" value={f.trading_cutoff} onChange={(e) => set("trading_cutoff", e.target.value)} data-testid="risk-cutoff" />
            </label>
            <div className="col-span-2 flex items-center gap-2">
              <button className="btn btn-primary" type="submit" data-testid="risk-save">{s.risk_settings.confirmed && !dirty ? "Re-confirm" : "Confirm risk settings"}</button>
              {msg && <span className="text-[11px] text-muted" role="status">{msg}</span>}
            </div>
          </form>
        </details>
        <p className="text-[11px] text-muted">Safeguards (daily loss, trade count, open positions, cooldown, stale data, cutoff, pause) only stop NEW paper entries. They never close real brokerage positions; this app has no broker order access.</p>
      </div>
    </Panel>
  );
}

export function StrategyPanel({ s, onChanged }: { s: AppState; onChanged: () => void }) {
  const tf = s.strategy.trigger_tf;
  const sens = s.strategy.sensitivity;
  const [err, setErr] = useState<string | null>(null);
  const apply = async (t: string, se: string) => {
    try { await api.setStrategy({ trigger_tf: t, sensitivity: se }); setErr(null); onChanged(); } catch (e) { setErr(String(e)); }
  };
  return (
    <Panel title="Strategy & data" right={<span className="num text-muted">{s.strategy.version}</span>}>
      <div className="grid grid-cols-2 gap-2 p-3">
        <label className="text-muted">Trigger timeframe
          <select className="input mt-0.5" value={tf} data-testid="strategy-tf" onChange={(e) => void apply(e.target.value, sens)}>
            <option>3m</option><option>5m</option><option>15m</option>
          </select>
        </label>
        <label className="text-muted">Signal sensitivity
          <select className="input mt-0.5" value={sens} data-testid="strategy-sens" onChange={(e) => void apply(tf, e.target.value)}>
            <option>conservative</option><option>standard</option><option>aggressive</option>
          </select>
        </label>
        <label className="col-span-2 flex items-center gap-2 text-muted">
          <input type="checkbox" checked={s.data.accept_delayed} onChange={(e) => void api.setData({ accept_delayed: e.target.checked }).then(onChanged)} />
          I accept DELAYED data for signals (off by default; delayed data is never treated as live)
        </label>
        <p className="col-span-2 text-[11px] text-muted">Higher timeframe confirmation: {s.strategy.htf}. Changing either setting creates a new strategy version label so journal entries stay attributable.</p>
        {err && <p className="col-span-2 text-down">{err}</p>}
      </div>
    </Panel>
  );
}
