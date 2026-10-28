"use client";
import type { Alert } from "@/lib/types";
import { istTime } from "@/lib/format";
import { Panel } from "./ui";

const TONE: Record<string, string> = { candidate: "text-blue", triggered: "text-amber", target_1: "text-up", target_2: "text-up", stopped: "text-down", data_health: "text-down", pause: "text-amber", paper_exit: "text-ink" };

export function Alerts({ alerts }: { alerts: Alert[] }) {
  return (
    <Panel title="Alerts" right={<span className="text-muted">deduplicated · state changes only</span>}>
      <ul className="scroll-y max-h-56 divide-y divide-[#18202a]" data-testid="alerts">
        {alerts.map((a, i) => (
          <li key={i} className="px-3 py-1.5"><span className="num text-muted">{istTime(a.ts)}</span> <span className={TONE[a.kind] ?? ""}>{a.message}</span></li>
        ))}
        {alerts.length === 0 && <li className="px-3 py-3 text-muted">No alerts. Alerts fire when a setup appears, triggers, invalidates, hits a target or stops, or data health changes.</li>}
      </ul>
    </Panel>
  );
}
