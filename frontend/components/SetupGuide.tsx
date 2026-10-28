"use client";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import { Panel } from "./ui";

/** Step-by-step checklist for turning on live data. Each step says what is missing and what to do about it. */
export function SetupGuide() {
  const { data, error } = usePoll(api.setup, 3000);
  if (!data) return <Panel title="Get live data working"><p className="p-3 text-muted">{error ?? "Loading…"}</p></Panel>;
  const live = data.provider === "kite";
  const steps = live ? data.steps : data.steps.filter((s) => s.id === "mode" || s.id === "risk");
  return (
    <Panel title="Get live data working" right={<span className="tag">{live ? "Kite live mode" : "Practice mode"}</span>}>
      <div className="space-y-3 p-3" data-testid="setup-guide">
        <ol className="space-y-1.5">
          {steps.map((s) => (
            <li key={s.id} className="flex items-start gap-2" data-testid={`setup-${s.id}`} data-done={s.done}>
              <span aria-hidden className={`mt-0.5 inline-flex h-4 w-4 flex-none items-center justify-center rounded-full border text-[10px] ${s.done ? "border-up text-up" : "border-line text-muted"}`}>{s.done ? "✓" : ""}</span>
              <span><b>{s.label}</b>{s.done ? <span className="text-up"> · done</span> : <span className="text-muted"> · {s.detail}</span>}</span>
            </li>
          ))}
        </ol>
        {live && data.next === "token" && data.connect_url && (
          <div className="flex flex-wrap items-center gap-2">
            <a className="btn btn-primary" href={data.connect_url} data-testid="connect-kite">Connect Kite (log in for today)</a>
            <span className="text-[11px] text-muted">You log in on Kite&apos;s own page. This app never sees your Kite password.</span>
          </div>
        )}
        {data.kite_message && <p className="text-amber" role="status">{data.kite_message}</p>}
        {live && (
          <p className="text-[11px] text-muted">One-time Kite app setting: in your app on developers.kite.trade, set the Redirect URL to <code className="num">{data.redirect_url_to_register}</code> so the login returns here by itself.</p>
        )}
        {!live && <p className="text-[11px] text-muted">Everything you see now is simulated practice data. Use the live launcher (see the README) once you have your Kite API key and secret.</p>}
      </div>
    </Panel>
  );
}
