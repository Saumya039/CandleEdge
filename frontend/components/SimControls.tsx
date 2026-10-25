"use client";
import { api } from "@/lib/api";
import type { AppState } from "@/lib/types";
import { Panel, SimTag } from "./ui";

export function SimControls({ s, onChanged }: { s: AppState; onChanged: () => void }) {
  if (!s.data.is_simulated) return null;
  const sim = s.simulator;
  const act = (a: string, v?: number) => () => void api.sim(a, v).then(onChanged);
  return (
    <Panel title="Simulator controls" right={<SimTag />}>
      <div className="space-y-2 p-3" data-testid="sim-controls">
        <div className="text-muted">Virtual clock {sim.virtual_now?.slice(11, 19)} IST · session {sim.sim_date} · seed {sim.seed} · speed {sim.speed}× (virtual s per real s)</div>
        <div className="flex flex-wrap gap-1.5">
          <button className="btn" onClick={act(sim.paused ? "resume" : "pause")}>{sim.paused ? "▶ Resume clock" : "⏸ Pause clock"}</button>
          {[10, 60, 300].map((v) => <button key={v} className="btn" onClick={act("speed", v)} aria-pressed={sim.speed === v}>{v}×</button>)}
          <button className="btn" onClick={act("skip", 600)} data-testid="sim-skip-10m">+10 min</button>
          <button className="btn" onClick={act("skip", 3600)} data-testid="sim-skip-1h">+1 h</button>
          <button className="btn btn-danger" onClick={act("outage", 300)} data-testid="sim-outage">Inject 5-min feed outage</button>
          <button className="btn" onClick={act("restart", (sim.seed ?? 0) + 1)} data-testid="sim-new-seed">New session (next seed)</button>
        </div>
        <p className="text-[11px] text-muted">The outage button drops the synthetic feed so you can see stale-data handling: signals are suppressed and gaps stay gaps.</p>
      </div>
    </Panel>
  );
}
