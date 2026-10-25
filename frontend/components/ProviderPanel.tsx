"use client";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import { Panel } from "./ui";

export function ProviderPanel() {
  const { data, error } = usePoll(api.provider, 5000);
  if (!data) return <Panel title="Provider"><p className="p-3 text-muted">{error ?? "Loading…"}</p></Panel>;
  const kite = data.setup.kite;
  const caps = data.capability_matrix as Record<string, string | boolean>[];
  const keys = ["live_ticks", "historical_ohlc", "option_chain", "instrument_master", "open_interest", "provider_greeks", "index_volume", "requires_auth", "order_api"];
  return (
    <div className="grid gap-3 xl:grid-cols-2" data-testid="provider-panel">
      <Panel title="Active provider" right={<span className="tag">{data.active.name}</span>}>
        <div className="space-y-1 p-3">
          <div>Status <b>{data.active.status}</b> · {data.active.connected ? "connected" : "not connected"} · {data.active.authenticated ? "authenticated" : "not authenticated"}</div>
          <div className="text-muted">{data.active.message}</div>
          {data.start_error && <div className="text-amber">Start error: {data.start_error}</div>}
          {data.active.missing_credentials.length > 0 && <div className="text-amber">Missing: {data.active.missing_credentials.join(", ")}</div>}
          <div className="text-muted">Transport: {data.active.transport}</div>
        </div>
      </Panel>
      <Panel title="Capability matrix">
        <div className="overflow-x-auto"><table className="t">
          <thead><tr><th>Capability</th>{caps.map((c) => <th key={String(c.provider)}>{String(c.provider)}</th>)}</tr></thead>
          <tbody>
            {keys.map((k) => <tr key={k}><td>{k.replace(/_/g, " ")}</td>{caps.map((c) => <td key={String(c.provider) + k}>{c[k] ? "yes" : "no"}</td>)}</tr>)}
            <tr><td>rate limits</td>{caps.map((c) => <td key={String(c.provider)} className="!whitespace-normal text-[11px] text-muted">{String(c.rate_limit_note)}</td>)}</tr>
          </tbody>
        </table></div>
      </Panel>
      <Panel title="Activate genuine live data (Zerodha Kite Connect)" className="xl:col-span-2">
        <div className="space-y-2 p-3">
          <p>Set these on the <b>server</b> (never in the browser): <code className="num">{kite.env.join("  ")}</code>. Restart the backend.</p>
          <ul className="list-disc pl-4 text-muted">{kite.needs.map((n) => <li key={n}>{n}</li>)}</ul>
          <p className="text-muted">{kite.order_permissions}</p>
          <p className="text-amber">The Kite adapter was built from the public API contract and tested against mocked responses only. Verify it against your live account and the current official docs before relying on it. LIVE is displayed only when the feed is authenticated and fresh.</p>
        </div>
      </Panel>
    </div>
  );
}
