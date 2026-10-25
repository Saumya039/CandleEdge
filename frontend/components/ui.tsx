"use client";
import type { ReactNode } from "react";
import { STATE_LABEL, dirLabel } from "@/lib/format";

export function Panel({ title, right, children, className = "" }: { title: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-h"><span>{title}</span><span className="flex items-center gap-2 normal-case tracking-normal">{right}</span></div>
      {children}
    </section>
  );
}

const STATE_COLOR: Record<string, string> = {
  CANDIDATE: "text-blue border-blue/50", TRIGGERED: "text-amber border-amber/60", TARGET_1: "text-up border-up/60",
  TARGET_2: "text-up border-up/60", STOPPED: "text-down border-down/60", INVALIDATED: "text-muted border-line",
  EXPIRED: "text-muted border-line", TIME_EXIT: "text-amber border-amber/50", WATCHING: "text-muted border-line", NO_TRADE: "text-muted border-line",
};
export function StateTag({ state }: { state: string }) {
  return <span className={`tag ${STATE_COLOR[state] ?? "text-muted"}`}>{(STATE_LABEL[state] ?? state.replace("_", " ")).toUpperCase()}</span>;
}
export function DirTag({ dir }: { dir: string }) {
  const up = dir === "BUY_CALL";
  return <span className={`tag ${up ? "text-up border-up/60" : "text-down border-down/60"}`}>{dirLabel(dir)}</span>;
}
export function SimTag({ label = "SIMULATED" }: { label?: string }) {
  return <span className="tag text-sim border-sim/60">{label}</span>;
}
export function Unavailable({ children = "Unavailable" }: { children?: ReactNode }) {
  return <span className="text-muted italic">{children}</span>;
}
export function Banner({ tone, children, testId }: { tone: "sim" | "warn" | "bad" | "info"; children: ReactNode; testId?: string }) {
  const c = { sim: "border-sim/60 bg-sim/10 text-sim", warn: "border-amber/60 bg-amber/10 text-amber", bad: "border-down/70 bg-down/10 text-down", info: "border-blue/50 bg-blue/10 text-blue" }[tone];
  return <div role={tone === "bad" ? "alert" : "status"} data-testid={testId} className={`rounded-md border px-3 py-1.5 text-[12px] font-medium ${c}`}>{children}</div>;
}
export const pnlClass = (v: number | null | undefined) => (v === null || v === undefined ? "" : v > 0 ? "text-up" : v < 0 ? "text-down" : "");
