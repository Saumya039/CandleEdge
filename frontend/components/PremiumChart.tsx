"use client";
import { ColorType, LineSeries, LineStyle, createChart, type IChartApi, type IPriceLine, type ISeriesApi, type Time, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Signal } from "@/lib/types";
import { istDateTime, istHM, num } from "@/lib/format";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import { Panel, SimTag, Unavailable } from "./ui";
import type { VisibleRange } from "./PriceChart";

export function PremiumChart({ signal, range }: { signal: Signal | null; range: VisibleRange }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const series = useRef<{ bid?: ISeriesApi<"Line">; ask?: ISeriesApi<"Line">; ltp?: ISeriesApi<"Line"> }>({});
  const lines = useRef<IPriceLine[]>([]);
  const { data } = usePoll(() => api.premium(signal!.id), 2000, !!signal, [signal?.id]);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#10151c" }, textColor: "#93a0b0", fontSize: 11 },
      grid: { vertLines: { color: "#18202a" }, horzLines: { color: "#18202a" } },
      rightPriceScale: { borderColor: "#212b37" },
      timeScale: { borderColor: "#212b37", timeVisible: true, tickMarkFormatter: (t: Time) => istHM(t as number) },
      localization: { timeFormatter: (t: Time) => istDateTime(t as number) },
    });
    series.current = {
      ask: chart.addSeries(LineSeries, { color: "#f06461", lineWidth: 1, title: "ask" }),
      bid: chart.addSeries(LineSeries, { color: "#2bb5a0", lineWidth: 1, title: "bid" }),
      ltp: chart.addSeries(LineSeries, { color: "#e8e8e8", lineWidth: 2, title: "ltp" }),
    };
    chartRef.current = chart;
    return () => { chart.remove(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    const s = series.current;
    if (!data || !s.ltp || !s.bid || !s.ask) return;
    const toPts = (k: "bid" | "ask" | "ltp") => {
      const seen = new Set<number>();
      const out: { time: UTCTimestamp; value: number }[] = [];
      for (const p of data.series) {
        const t = Math.floor(new Date(p.ts).getTime() / 1000);
        const v = p[k];
        if (v === null || seen.has(t)) continue;
        seen.add(t);
        out.push({ time: t as UTCTimestamp, value: v });
      }
      return out.sort((a, b) => a.time - b.time);
    };
    s.bid.setData(toPts("bid")); s.ask.setData(toPts("ask")); s.ltp.setData(toPts("ltp"));
    lines.current.forEach((l) => s.ltp!.removePriceLine(l));
    lines.current = [];
    if (signal) {
      const p = signal.plan;
      const add = (price: number, color: string, title: string, st = LineStyle.Dashed) =>
        lines.current.push(s.ltp!.createPriceLine({ price, color, lineWidth: 1, lineStyle: st, axisLabelVisible: true, title }));
      add(p.entry_premium_assumed, "#6cb2ff", "paper entry (ask+slip)");
      add(p.premium_stop, "#f06461", "premium risk level", LineStyle.Solid);
      add(p.premium_target1, "#2bb5a0", "T1 est.");
      add(p.premium_target2, "#2bb5a0", "T2 est.", LineStyle.Dotted);
    }
  }, [data, signal]);

  useEffect(() => {
    if (!range || !chartRef.current) return;
    try { chartRef.current.timeScale().setVisibleRange({ from: range.from as UTCTimestamp, to: range.to as UTCTimestamp }); } catch { /* no overlapping data yet */ }
  }, [range]);

  const q = signal?.plan.quote;
  return (
    <Panel title={<span>Option premium {signal ? `· ${signal.plan.contract.symbol}` : ""}</span>} right={signal?.plan.quote.status === "SIMULATED" ? <SimTag /> : null}>
      <div className="relative">
        <div ref={host} className="h-[220px] w-full" data-testid="premium-chart" />
        {!signal && <div className="absolute inset-0 grid place-items-center px-6 text-center text-muted">No selected contract. A contract is chosen only when a setup passes all liquidity and freshness filters.</div>}
        {signal && (!data || data.series.length === 0) && <div className="absolute inset-0 grid place-items-center text-muted">Waiting for option snapshots…</div>}
      </div>
      <div className="flex flex-wrap gap-x-4 px-3 py-1.5 text-[11px] text-muted">
        {signal && q ? (
          <>
            <span>Bid/ask at signal: <b className="num text-ink">{num(q.bid)} / {num(q.ask)}</b> (spread {signal.plan.spread_pct.toFixed(2)}%)</span>
            <span>Series is built from option-chain snapshots polled by the engine, not exchange candles.</span>
          </>
        ) : <Unavailable>Premium series unavailable</Unavailable>}
      </div>
    </Panel>
  );
}
